classdef Dataset < handle
    %LBD.DATASET  In-memory content of one LBD (.lbd) file.
    %
    %   d = lbd.Dataset("Resonator power sweep");
    %   d.addAxis("power", -40:4:0, Unit="dBm", Label="Power");
    %   d.addAxis("freq", linspace(4e9, 8e9, 401), Unit="Hz", Label="Frequency");
    %   d.addValue("S21", s21, ["power" "freq"]);      % size(s21) == [11 401]
    %   d.addAxis("state", [], Elements=["ground" "excited"]);   % named positions, numbered 0, 1
    %   d.addValue("bloch", b, "amp", Shape=3, Elements=["x" "y" "z"]);   % size(b) == [21 3]
    %   d.addValue("S21b", [], ["power" "freq"], Dtype="complex128");   % filled later by write
    %   d.write(power=3, S21b=trace);                   % a trace (power 3, every freq)
    %   d.addGroup("scan");                             % a variable sweep (format 2.0):
    %   d.addAxis("A", [], Group="scan"); d.addAxis("B", [], Group="scan");   % B chosen per A
    %   d.addValue("f", [], ["A" "B"]);                 % one entry per (A, B) point
    %   i = d.write(A=3); d.write(Parent=i, B=[15 25], f=[1 2]);
    %   m = d.toDense("f");                             % the full rectangle, gaps NaN
    %   d.Meta.T_mK = 12;
    %   d.save("sweep.lbd");
    %
    %   d = lbd.load("sweep.lbd");
    %   d.Values.S21.Data
    %
    %   See spec/LBD-v1.md for the file format.

    properties
        Title (1,1) string = ""
        Description (1,1) string = ""
        Meta (1,1) struct = struct()   % free metadata; nested structs become sub-groups
        Plot = []                      % struct: default plot spec, stored as JSON
        Style = []                     % struct: per-file style override, stored as JSON
        StyleName string = string.empty
        Matplotlib string = string.empty  % matplotlib version that last wrote the saved view (kept as is)
        % When the data was created: ISO-8601 text with a UTC offset, or a datetime. Empty: save
        % fills in the time of the first save; a loaded file keeps its time, and saving keeps it.
        Created = string.empty
    end

    properties (SetAccess = private)
        % Axes.<name> = struct(Name, Data, Unit, Label, Elements, Role, Grows, Group, Parent): the
        % sweep axes. Elements, a text per position (string.empty: numbered); Grows, true for an
        % axis whose points write adds (addAxis(..., Grows=true)); Group, the axis group it is in
        % ("" for a fixed axis), whose points Data lists one per point of its level; Parent, for
        % each point of a group's axis below its first, the index (from 1) of its point in the
        % level above ([] otherwise). Role is "" (a data point's dimensions aren't axes).
        Axes (1,1) struct = struct()
        % Groups.<name> = struct(Name, Order): axis groups (format 2.0), Order their axes, outer
        % to inner
        Groups (1,1) struct = struct()
        % Values.<name> = struct(Name, Data, Axes, Dims, Unit, Label, Shape, Dtype, PointShape,
        % Elements, Measured): Axes, the sweep axes it depends on; Dims, how the sweep part is
        % stored, a cell with the axis names of each dimension ("A" for a fixed axis, ["A" "B"]
        % for the points of a group's level); PointShape, the size of one data point ([] for a
        % number); Shape, the data's size (the Dims' lengths, then PointShape); Elements, a cell
        % with each data point dimension's texts (string.empty: numbered); Measured, for an
        % integer or logical value filled by write, true where something was written ([] for
        % every other value: NaN means "not measured")
        Values (1,1) struct = struct()
        Writer string = string.empty
        LbdVersion (1,1) string = "1.2"
        Path string = string.empty
        % The measurement's identity (a UUID version 7): made at the first save, kept when the
        % file is saved again to the same place, new when it is saved to another file (or by
        % newId), so a copy made by a program is a measurement of its own. Empty: not saved yet,
        % or a file written before format 1.1.
        Id string = string.empty
        % The Id of the file this one was made from (saved to another file, newId), if any.
        ParentId string = string.empty
    end

    properties (Hidden)
        % lbd.Writer: values without data take no memory (their data is in the file)
        LiveWriting (1,1) logical = false
        Placeholders string = strings(1, 0)
        % each group level's points by (parent, coordinate): struct(n, map) per axis
        Lookups (1,1) struct = struct()
        % lbd.open: the file its values are read from (lbd.LazySource), or [] after lbd.load
        Source = []
    end

    methods
        function obj = Dataset(title, description, opts)
            arguments
                title (1,1) string = ""
                description (1,1) string = ""
                opts.Created = string.empty
            end
            obj.Title = title;
            obj.Description = description;
            if ~isempty(opts.Created)
                obj.Created = lbd_created_text(opts.Created);
            end
        end

        function group = addGroup(obj, name)
            %ADDGROUP  Add an axis group (format 2.0): a sweep whose inner points depend on the
            %   outer ones (B chosen per A, a different number of B per A, adaptive points).
            %   Add its axes next, outer to inner, with addAxis(name, [], Group=...); write adds
            %   their points by coordinate, and only measured points are stored. LBD older than
            %   1.3 can't read such a file: use fixed axes when every combination is planned.
            %   d.addGroup("scan"); d.addAxis("power", [], Group="scan"); d.addAxis("freq", [], Group="scan")
            arguments
                obj
                name (1,1) string
            end
            obj.checkNewName(name);
            group = struct('Name', name, 'Order', strings(1, 0));
            obj.Groups.(name) = group;
        end

        function axis = addAxis(obj, name, data, opts)
            %ADDAXIS  Add a 1-D real axis.
            %   d.addAxis("power", -40:4:0, Unit="dBm")
            %   d.addAxis("state", [], Elements=["ground" "excited"])   % numbered 0, 1
            %   d.addAxis("time", [], Unit="s", Grows=true)   % points added by write
            %   d.addAxis("B", [], Group="scan")              % an axis of a group: write adds its points
            arguments
                obj
                name (1,1) string
                data = []
                opts.Unit (1,1) string = ""
                opts.Label string = string.empty
                opts.Elements = string.empty
                opts.Grows (1,1) logical = false
                opts.Group (1,1) string = ""
            end
            obj.checkNewName(name);
            if strlength(opts.Group) > 0
                g = opts.Group;
                if ~isfield(obj.Groups, g)
                    error('lbd:invalid', 'axis "%s": there is no group "%s"; add it first with addGroup("%s")', name, g, g);
                end
                if ~isempty(data) || ~isempty(opts.Elements) || opts.Grows
                    error('lbd:invalid', ['axis "%s" is in group "%s": give no data, Elements or Grows; write adds ' ...
                        'its points by coordinate'], name, g);
                end
                label = opts.Label;
                if isempty(label), label = name; end
                parent = [];
                if ~isempty(obj.Groups.(g).Order), parent = zeros(0, 1, 'int64'); end
                axis = lbd.Dataset.axisStruct(name, zeros(0, 1), opts.Unit, label, string.empty, g, parent);
                obj.Groups.(g).Order(end+1) = name;
                obj.Axes.(name) = axis;
                return
            end
            if opts.Grows
                if ~isempty(data) || ~isempty(opts.Elements)
                    error('lbd:invalid', 'axis "%s" grows: give no data or Elements; write adds its points', name);
                end
                label = opts.Label;
                if isempty(label), label = name; end
                axis = lbd.Dataset.axisStruct(name, zeros(0, 1), opts.Unit, label, string.empty, "", []);
                axis.Grows = true;
                obj.Axes.(name) = axis;
                return
            end
            elements = lbd.Dataset.checkElements(opts.Elements, [], sprintf('axis "%s"', name));
            if isempty(data)
                if isempty(elements)
                    error('lbd:invalid', 'axis "%s" needs its coordinates (data) or its Elements', name);
                end
                data = int64(0:numel(elements) - 1);
            end
            if ~isvector(data) && ~isempty(data)
                error('lbd:invalid', 'axis "%s" must be 1-D, got size %s', name, mat2str(size(data)));
            end
            if ~(isnumeric(data) && isreal(data))
                error('lbd:invalid', 'axis "%s" must be real numeric, got %s', name, class(data));
            end
            label = opts.Label;
            if isempty(label), label = name; end
            if ~isempty(elements)
                lbd.Dataset.checkElements(elements, numel(data), sprintf('axis "%s"', name));
            end
            axis = lbd.Dataset.axisStruct(name, data(:), opts.Unit, label, elements, "", []);
            obj.Axes.(name) = axis;
        end

        function value = addValue(obj, name, data, axes, opts)
            %ADDVALUE  Add an N-D value. AXES lists the axes it depends on, outer to inner: a
            %   fixed axis is one dimension; axes of a group are one dimension together, the
            %   points of their level (["A" "B"] of a group A → B → C; the group's name: all).
            %   d.addValue("S21", s21, ["power" "freq"])
            %   d.addValue("trace", y, "freq")
            %   d.addValue("fit_Q", 1.2e4)                 % scalar, no axes
            %   d.addValue("v", x, "freq", Dtype="float32")
            %   d.addValue("bloch", b, "amp", Shape=3, Elements=["x" "y" "z"])   % a vector per point
            %   d.addValue("cov", c, "amp", Shape=[2 2], Elements={["I" "Q"], ["I" "Q"]})
            %   d.addValue("S21", [], ["power" "freq"], Dtype="complex128")   % filled by write
            %   Each data point is one number unless Shape says otherwise; DATA's dimensions are
            %   the value's axes first, then the data point's. DATA empty ([]): every point
            %   starts as NaN (not measured yet), or for integers and logicals as 0 with
            %   Measured false; write fills it.
            arguments
                obj
                name (1,1) string
                data = []
                axes = string.empty
                opts.Unit (1,1) string = ""
                opts.Label string = string.empty
                opts.Dtype (1,1) string = "auto"
                opts.Shape double = zeros(1, 0)
                opts.Elements = []
            end
            obj.checkNewName(name);
            dims = obj.parseDims(lbd.Dataset.axesList(axes), sprintf('value "%s"', name));
            axesList = [strings(1, 0) dims{:}];
            point = opts.Shape(:)';
            if any(point < 1 | point ~= round(point))
                error('lbd:invalid', 'value "%s": Shape must hold whole numbers of at least 1, not %s', name, mat2str(opts.Shape));
            end
            nd = numel(dims);
            total = nd + numel(point);
            measured = [];
            placeholder = false;
            if isempty(data)                   % filled later by write: "not measured yet"
                shape = [zeros(1, 0) cellfun(@(dm) obj.dimLength(dm), dims), point];
                kind = opts.Dtype;
                if kind == "auto", kind = "float64"; end
                [data, measured] = lbd.Dataset.notMeasured(shape, kind, name, obj.LiveWriting);
                placeholder = obj.LiveWriting;
                dtypeName = kind;
            else
                data = lbd.Dataset.coerce(data, opts.Dtype, name);
                dtypeName = string.empty;
            end
            if ~isempty(dtypeName)
                % the shape is known: no data to look at
            elseif total == 0
                if ~isscalar(data)
                    error('lbd:invalid', 'value "%s" is not scalar, so it needs axes', name);
                end
                shape = zeros(1, 0);
            elseif total == 1
                if ~isvector(data)
                    error('lbd:invalid', ['value "%s" has %d dimension(s) but 1 axis was given; if each ' ...
                        'data point holds several numbers, say so with Shape'], name, ndims(data));
                end
                wasComplex = ~isreal(data);
                data = data(:);
                % data(:) drops an all-zero imaginary part; keep complex data complex
                if wasComplex, data = complex(data); end
                shape = numel(data);
            else
                if ndims(data) > total
                    if isempty(point)
                        error('lbd:invalid', ['value "%s" has %d dimension(s) but %d axes were given; if each ' ...
                            'data point holds several numbers, say so with Shape=%s'], name, ndims(data), nd, ...
                            mat2str(size(data, nd+1:ndims(data))));
                    end
                    error('lbd:invalid', 'value "%s" has %d dimension(s), but its axes and Shape make %d', ...
                        name, ndims(data), total);
                end
                shape = size(data, 1:total);
            end
            growing = axesList(arrayfun(@(a) isfield(obj.Axes, a) && obj.Axes.(a).Grows, axesList));
            if numel(growing) > 1 || (~isempty(growing) && axesList(1) ~= growing(1))
                error('lbd:invalid', 'value "%s": a growing axis must be its first axis, and only one (here %s)', ...
                    name, strjoin(axesList, ", "));
            end
            for i = 1:nd
                dm = dims{i};
                n = obj.dimLength(dm);
                if n ~= shape(i)
                    hint = '';
                    if ~isempty(point) && ~isequal(shape(nd+1:end), point)
                        hint = '; the value''s axes come first, then the data point (e.g. transpose it)';
                    end
                    if obj.isGroupDim(dm)
                        what = sprintf('the level %s of group "%s" has %d points', strjoin(dm, ","), obj.Axes.(dm(1)).Group, n);
                    else
                        what = sprintf('axis "%s" has length %d', dm, n);
                    end
                    error('lbd:invalid', 'value "%s": dimension %d has size %d but %s%s', name, i, shape(i), what, hint);
                end
            end
            if ~isempty(point) && ~isequal(shape(nd+1:end), point)
                error('lbd:invalid', 'value "%s": its data points have size %s, not Shape=%s', ...
                    name, mat2str(shape(nd+1:end)), mat2str(point));
            end
            named = lbd.Dataset.valueElements(opts.Elements, point, name);
            pointNames = name + "_dim" + string(1:numel(point));
            for k = 1:numel(point)
                if isfield(obj.Axes, pointNames(k)) || isfield(obj.Values, pointNames(k)) || isfield(obj.Groups, pointNames(k))
                    error('lbd:invalid', ['value "%s" needs the name "%s" for a dimension of its data points in the ' ...
                        'file, but it is already used; rename that axis or value'], name, pointNames(k));
                end
            end
            label = opts.Label;
            if isempty(label), label = name; end
            if isempty(dtypeName), dtypeName = lbd_dtype_name(data); end
            value = struct('Name', name, 'Data', data, 'Axes', axesList, 'Dims', {dims}, 'Unit', opts.Unit, ...
                'Label', label, 'Shape', shape, 'Dtype', dtypeName, 'PointShape', point, ...
                'Elements', {named}, 'Measured', measured);
            obj.Values.(name) = value;
            if placeholder, obj.Placeholders(end+1) = name; end
        end

        function item = get(obj, name)
            %GET  Return the value or axis struct called NAME.
            name = string(name);
            if isfield(obj.Values, name)
                item = obj.Values.(name);
            elseif isfield(obj.Axes, name)
                item = obj.Axes.(name);
            else
                error('lbd:notFound', 'no value or axis named "%s"', name);
            end
        end

        function index = write(obj, varargin)
            %WRITE  Put measured data into values made by addValue: a point, a trace, a whole
            %   map, or several values at once, at the place the axes say.
            %   d.write(A=3, B=[15 25], f=[x1 x2])    % axes of a group: coordinates (the same
            %                                          % coordinates are the same point)
            %   i = d.write(A=3); d.write(Parent=i, B=25, f=x)   % under the point write returned
            %   d.write(power=3, S21=trace)            % a trace: power 3, every frequency
            %   d.write(power=3, freq=7, S21=z, T=t)   % a point, and T at power 3
            %   d.write(state="excited", power=1, n=7) % a position by its element
            %   d.write(time=12.5, T=4.2)              % a growing axis: adds a point
            %   d.write("if", 3, "S21", z)             % any name, as text
            %   A fixed axis takes an index (1 = its first point) or one of its elements; a
            %   growing axis its coordinate(s); a value its data, sized as the value's axes that
            %   weren't given (and its data point, always whole), in order. Writing again
            %   replaces. Returns the index (from 1) of the group's point at the deepest level
            %   given (a column for several points), for Parent=; a struct by group name for
            %   several groups; [] without a group.
            if ~isempty(obj.Source), obj.Source.check("write"); end
            plan = obj.planWrite(varargin);
            if ~isempty(obj.Source) && (~isempty(plan.grow) || ~isempty(plan.levels))
                error('lbd:invalid', ['write: the file is opened with lbd.open, where write puts data at points ' ...
                    'that exist; to add points (a growing axis, a group''s new points) use lbd.load, or lbd.Writer']);
            end
            obj.applyWrite(plan);
            index = plan.result;
        end

        function c = coords(obj, name)
            %COORDS  Each point's coordinates of value NAME: a struct with one array per axis,
            %   along its dimension of the data. A fixed axis gives its coordinates; the points
            %   of a group's level, every point's coordinate on each axis down to it.
            %   c = d.coords("f"); scatter(c.A, c.B, [], d.Values.f.Data)
            v = obj.valueNamed(name);
            c = struct();
            for i = 1:numel(v.Dims)
                dm = v.Dims{i};
                if ~obj.isGroupDim(dm)
                    c.(dm) = obj.Axes.(dm).Data(:);
                    continue
                end
                chain = obj.ancestors(dm);
                for m = 1:numel(dm)
                    c.(dm(m)) = obj.Axes.(dm(m)).Data(chain{m});
                end
            end
        end

        function r = rows(obj, name, opts)
            %ROWS  Value NAME row by row: a cell with one row per point of By's level (per
            %   position of a fixed axis By): {key, dataset; ...}. The key is the coordinate(s)
            %   down to By; the dataset (an lbd.Dataset, a copy) holds what lies inside.
            %   r = d.rows("f", By="A"); for k = 1:size(r, 1), plot(r{k,2}.Axes.B.Data, r{k,2}.Values.f.Data); end
            arguments
                obj
                name (1,1) string
                opts.By (1,1) string
            end
            v = obj.valueNamed(name);
            by = opts.By;
            pos = find(cellfun(@(dm) any(dm == by), v.Dims), 1);
            if isempty(pos)
                error('lbd:invalid', 'rows: "%s" doesn''t lie on "%s" (its axes: %s)', name, by, strjoin(v.Axes, ", "));
            end
            dm = v.Dims{pos};
            if ~obj.isGroupDim(dm)
                n = numel(obj.Axes.(by).Data);
                r = cell(n, 2);
                for i = 1:n
                    r{i, 1} = obj.Axes.(by).Data(i);
                    r{i, 2} = obj.part(v, pos, {"index", i});
                end
                return
            end
            j = find(dm == by);
            outer = dm(1:j);
            keyChain = obj.ancestors(outer);
            n = obj.dimLength(outer);
            r = cell(n, 2);
            anc = obj.ancestors(dm);
            anc = anc{j};
            for p = 1:n
                r{p, 1} = arrayfun(@(m) obj.Axes.(outer(m)).Data(keyChain{m}(p)), 1:j);
                if j == numel(dm)
                    r{p, 2} = obj.part(v, pos, {"point", p});
                else
                    r{p, 2} = obj.part(v, pos, {"under", j, p, find(anc == p)});
                end
            end
        end

        function m = toDense(obj, name, opts)
            %TODENSE  Value NAME as a full rectangle: an lbd.Dataset with fixed axes only.
            %   A group stores only the measured points ("sparse"); this places them in the full
            %   rectangle ("dense"). Each axis's ticks are the sorted distinct coordinates of the
            %   value's points; cells not measured hold NaN (0 / false with Measured for integers
            %   and logicals). It doesn't interpolate; always a copy.
            %   m = d.toDense("f");
            %   m = d.toDense("f", Round=9);       % merge coordinates that differ only by rounding
            %   m = d.toDense("f", RTol=1e-9);     % ... as isclose: |a - b| <= ATol + RTol*|b|
            %   m = d.toDense("f", Limit=Inf);     % no size limit (default 1e8 cells)
            arguments
                obj
                name (1,1) string
                opts.Round double = []
                opts.RTol double = []
                opts.ATol double = []
                opts.Limit (1,1) double = 1e8
            end
            v = obj.valueNamed(name);
            if ~isempty(opts.Round) && (~isempty(opts.RTol) || ~isempty(opts.ATol))
                error('lbd:invalid', 'toDense: give Round or RTol / ATol, not both');
            end
            ticks = struct();
            where = cell(1, numel(v.Dims));
            for i = 1:numel(v.Dims)
                dm = v.Dims{i};
                if ~obj.isGroupDim(dm)
                    ticks.(dm) = obj.Axes.(dm).Data(:);
                    continue
                end
                chain = obj.ancestors(dm);
                w = cell(1, numel(dm));
                for k = 1:numel(dm)
                    [ticks.(dm(k)), w{k}] = lbd.Dataset.ticksOf(obj.Axes.(dm(k)).Data(chain{k}), dm(k), opts);
                end
                where{i} = w;
            end
            T = arrayfun(@(a) numel(ticks.(a)), v.Axes);
            shape = [T v.PointShape];
            cells = prod(shape);
            if cells > opts.Limit
                bits = str2double(regexp(v.Dtype, '\d+', 'match', 'once'));
                if isnan(bits), bits = 8; end                    % bool: one byte
                bytes = cells * bits / 8;
                error('lbd:invalid', ['toDense: "%s" as a rectangle %s has %d cells (%.2f GB), more than Limit=%g. ' ...
                    'Read it row by row with rows(..., By=...), or give Limit=Inf'], name, mat2str(shape), cells, bytes / 1e9, opts.Limit);
            end
            dimLens = [zeros(1, 0) cellfun(@(dm) obj.dimLength(dm), v.Dims)];
            D = prod(dimLens);
            P = prod(v.PointShape);
            grids = cell(1, numel(dimLens));
            if numel(dimLens) == 1
                grids{1} = (1:D)';
            elseif numel(dimLens) > 1
                ranges = arrayfun(@(n) 1:n, dimLens, 'UniformOutput', false);
                [grids{:}] = ndgrid(ranges{:});
            end
            subs = {};
            for i = 1:numel(dimLens)
                if isempty(where{i})
                    subs{end+1} = grids{i}(:); %#ok<AGROW>
                else
                    for k = 1:numel(where{i})
                        subs{end+1} = where{i}{k}(grids{i}(:)); %#ok<AGROW>
                    end
                end
            end
            if isempty(subs)
                lin = 1;
            elseif numel(subs) == 1
                lin = subs{1};
            else
                lin = sub2ind(T, subs{:});
            end
            if numel(unique(lin)) < numel(lin)
                error('lbd:invalid', ['toDense: two points of "%s" fall into one cell: merging must not drop a ' ...
                    'result. Use a smaller Round / RTol / ATol'], name);
            end
            data = lbd.Dataset.whole(v.Data);              % opened with lbd.open: read now
            out = lbd.Dataset.fillLike(data, [max(prod(T), 1) P]);
            out(lin, :) = reshape(data, D, P);
            out = reshape(out, [shape ones(1, max(0, 2 - numel(shape)))]);
            if startsWith(v.Dtype, "complex"), out = complex(out); end
            measured = [];
            if ~isfloat(data)
                mask = false(max(prod(T), 1), P);
                if isempty(v.Measured), src = true(D, P); else, src = reshape(lbd.Dataset.whole(v.Measured), D, P); end
                mask(lin, :) = src;
                if ~all(mask(:)), measured = reshape(mask, size(out)); end
            end
            m = lbd.Dataset(obj.Title);
            for a = v.Axes
                src = obj.Axes.(a);
                el = string.empty;
                if strlength(src.Group) == 0, el = src.Elements; end
                m.Axes.(a) = lbd.Dataset.axisStruct(a, ticks.(a), src.Unit, src.Label, el, "", []);
            end
            m.Values.(name) = struct('Name', name, 'Data', out, 'Axes', v.Axes, ...
                'Dims', {arrayfun(@(a) a, v.Axes, 'UniformOutput', false)}, 'Unit', v.Unit, 'Label', v.Label, ...
                'Shape', shape, 'Dtype', v.Dtype, 'PointShape', v.PointShape, 'Elements', {v.Elements}, ...
                'Measured', measured);
        end

        function close(obj)
            %CLOSE  Close the file of a dataset opened with lbd.open: what was read stays usable;
            %   reading more is refused. Nothing to do for a loaded dataset.
            if ~isempty(obj.Source), obj.Source.close(); end
        end

        function newId(obj)
            %NEWID  Make this dataset a measurement of its own: a new Id; the old one becomes
            %   ParentId. Takes effect when it is saved.
            if ~isempty(obj.Id) && strlength(obj.Id) > 0
                obj.ParentId = obj.Id;
            end
            obj.Id = lbd_uuid7();
        end

        function path = save(obj, path, opts)
            %SAVE  Write the dataset to PATH (.lbd). Compression=true gzips large arrays.
            %   The file is written under a temporary name and then renamed, so a viewer
            %   never sees a half-written file. A dataset opened with lbd.open(..., Mode="r+"):
            %   d.save() rewrites its description, metadata and saved view in the file;
            %   d.save("copy.lbd") copies it piece by piece.
            arguments
                obj
                path (1,1) string = ""
                opts.Compression (1,1) logical = false
            end
            if ~isempty(obj.Source)
                obj.Source.check("save");
                if strlength(path) == 0 || lbd.Dataset.samePath(path, obj.Source.Path)
                    obj.saveInPlace();
                    path = obj.Source.Path;
                    return
                end
            end
            if strlength(path) == 0
                error('lbd:invalid', 'save needs a path, e.g. d.save("sweep.lbd")');
            end
            [~, ~, ext] = fileparts(path);
            if lower(ext) == ".writing"
                error('lbd:invalid', '%s: a ".writing" file is written only by lbd.Writer; save to the .lbd name', path);
            end
            if lower(ext) ~= ".lbd"
                warning('lbd:extension', '%s: LBD files should use the .lbd extension', path);
            end
            anames = fieldnames(obj.Axes);
            for i = 1:numel(anames)
                if obj.Axes.(anames{i}).Grows && isempty(obj.Axes.(anames{i}).Data)
                    error('lbd:invalid', 'the growing axis "%s" has no points yet; write some before saving', anames{i});
                end
            end
            vnames = fieldnames(obj.Values);
            for i = 1:numel(vnames)
                if isempty(obj.Values.(vnames{i}).Data) && prod(obj.Values.(vnames{i}).Shape) > 0
                    error('lbd:invalid', 'value "%s" was not loaded; load the file fully to re-save it', vnames{i});
                end
            end
            % Check the saved view before anything is written.
            if ~isempty(obj.Plot), lbd_to_json(obj.Plot, "Plot"); end
            if ~isempty(obj.Style), lbd_to_json(obj.Style, "Style"); end
            if ~isempty(obj.StyleName) && (~isscalar(obj.StyleName) || strlength(obj.StyleName) == 0)
                error('lbd:invalid', 'StyleName must be one non-empty name (or empty to remove it)');
            end
            % The identity: kept when saved again to the same file; new (the old one as ParentId)
            % when saved to another file; made now for a dataset never saved.
            id = obj.Id;
            parent = obj.ParentId;
            if isempty(id) || strlength(id) == 0
                id = lbd_uuid7();
            elseif ~isempty(obj.Path) && ~lbd.Dataset.samePath(obj.Path, path)
                parent = id;
                id = lbd_uuid7();
            end
            tmp = path + ".tmp-" + string(feature('getpid'));
            try
                obj.writeFile(tmp, opts.Compression, id, parent);
                % On Windows the file can't be replaced while another program has it open, even
                % for a moment (LBD Viewer reading the new version, a sync client, an antivirus
                % scan): try again for up to 3 s.
                started = tic;
                while true
                    [ok, msg] = movefile(tmp, path, 'f');
                    if ok, break; end
                    if ~ispc || toc(started) > 3
                        error('lbd:write', ['can''t write %s: %s. If another program has it open ' ...
                            '(e.g. LBD Viewer or a sync client), close it there and save again.'], path, msg);
                    end
                    pause(0.05);
                end
            catch err
                if isfile(tmp), delete(tmp); end
                rethrow(err);
            end
            if ~isempty(obj.Source), return; end     % a copy of an opened file: this one stays as it is
            obj.Path = path;
            obj.Id = id;
            obj.ParentId = parent;
        end

        function disp(obj)
            fprintf('  lbd.Dataset "%s"\n', obj.Title);
            gn = fieldnames(obj.Groups);
            for i = 1:numel(gn)
                fprintf('    group %s: %s\n', gn{i}, strjoin(obj.Groups.(gn{i}).Order, " -> "));
            end
            an = fieldnames(obj.Axes);
            for i = 1:numel(an)
                a = obj.Axes.(an{i});
                fprintf('    axis  %s[%d] %s\n', a.Name, numel(a.Data), a.Unit);
            end
            vn = fieldnames(obj.Values);
            for i = 1:numel(vn)
                v = obj.Values.(vn{i});
                fprintf('    value %s(%s) %s %s\n', v.Name, strjoin(v.Axes, ","), v.Dtype, v.Unit);
            end
        end
    end

    methods (Access = private)
        function checkNewName(obj, name)
            if isempty(regexp(name, '^[A-Za-z][A-Za-z0-9_]{0,62}$', 'once'))
                error('lbd:invalid', ['invalid name "%s": must start with a letter and contain only ' ...
                    'letters, digits and ''_'' (max 63)'], name);
            end
            if isfield(obj.Axes, name) || isfield(obj.Values, name) || isfield(obj.Groups, name)
                error('lbd:invalid', 'name "%s" is already used by an axis, group or value', name);
            end
            vn = string(fieldnames(obj.Values))';
            for k = vn
                if any(lbd.Dataset.pointNames(obj.Values.(k)) == name)
                    error('lbd:invalid', 'name "%s" is used in the file for a dimension of the data points of "%s"', name, k);
                end
            end
        end

        function writeFile(obj, path, compression, id, parent)
            % when the data was created: kept as set (also as read by load); not set: this first save
            if isempty(obj.Created) || (isstring(obj.Created) && strlength(obj.Created) == 0)
                created = string(datetime('now', 'TimeZone', 'local', 'Format', "yyyy-MM-dd'T'HH:mm:ssxxx"));
            else
                created = lbd_created_text(obj.Created);
            end
            v = lbd.version();
            writer = "matlab lbd " + v.package;
            fid = H5F.create(path, 'H5F_ACC_TRUNC', 'H5P_DEFAULT', 'H5P_DEFAULT');
            closer = onCleanup(@() H5F.close(fid));
            lbd_write_attr(fid, 'lbd_format', "LBD");
            ver = lbd_version_needed(obj);
            lbd_write_attr(fid, 'lbd_version', ver);
            lbd_write_attr(fid, 'title', obj.Title);
            lbd_write_attr(fid, 'description', obj.Description);
            lbd_write_attr(fid, 'created', created);
            lbd_write_attr(fid, 'writer', writer);
            lbd_write_attr(fid, 'id', id);
            if ~isempty(parent) && strlength(parent) > 0
                lbd_write_attr(fid, 'parent_id', parent);
            end

            gid = H5G.create(fid, 'axes', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
            fa = obj.fileAxes();
            for i = 1:numel(fa)
                a = fa{i};
                did = lbd_write_dataset(gid, a.Name, a.Data, 1, compression);
                lbd_write_attr(did, 'unit', a.Unit);
                lbd_write_attr(did, 'label', a.Label);
                if isfield(a, 'Elements') && ~isempty(a.Elements)
                    lbd.Dataset.checkElements(a.Elements, numel(a.Data), sprintf('axis "%s"', a.Name));
                    lbd_write_attr(did, 'elements', string(a.Elements), true);
                end
                if isfield(a, 'Role') && strlength(a.Role) > 0
                    lbd_write_attr(did, 'role', a.Role);
                end
                H5D.close(did);
            end
            for gname = string(fieldnames(obj.Groups))'     % axis groups (spec 1.8), level by level
                g = obj.Groups.(gname);
                ggid = H5G.create(gid, char(gname), 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
                lbd_write_attr(ggid, 'order', strjoin(g.Order, ","));
                for k = 1:numel(g.Order)
                    a = obj.Axes.(g.Order(k));
                    did = lbd_write_dataset(ggid, a.Name, a.Data, 1, compression);
                    lbd_write_attr(did, 'unit', a.Unit);
                    lbd_write_attr(did, 'label', a.Label);
                    H5D.close(did);
                    if k > 1                                 % from 0 in the file
                        H5D.close(lbd_write_dataset(ggid, a.Name + "._parent", int64(a.Parent(:)) - 1, 1, compression));
                    end
                end
                H5G.close(ggid);
            end
            H5G.close(gid);

            gid = H5G.create(fid, 'values', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
            vn = fieldnames(obj.Values);
            for i = 1:numel(vn)
                val = obj.Values.(vn{i});
                data = val.Data;
                if isa(data, 'lbd.OnDisk')           % opened with lbd.open: copied inside HDF5, never read whole
                    where = data.Where;
                    obj.Source.run(@(src) copyValue(src, where, gid, val.Name));
                    did = H5D.open(gid, char(val.Name));
                    for a = ["unit" "label" "axes"]
                        try, H5A.delete(did, char(a)); catch, end
                    end
                    isBool = false;                  % lbd_bool is copied with it
                else
                    if startsWith(val.Dtype, "complex") && isreal(data)
                        data = complex(data);           % MATLAB drops an all-zero imaginary part
                    end
                    isBool = islogical(data);
                    if isBool, data = uint8(data); end
                    did = lbd_write_dataset(gid, val.Name, data, numel(val.Dims) + numel(val.PointShape), compression);
                end
                lbd_write_attr(did, 'unit', val.Unit);
                lbd_write_attr(did, 'label', val.Label);
                lbd_write_attr(did, 'axes', strjoin([val.Axes lbd.Dataset.pointNames(val)], ","));
                if isBool, lbd_write_attr(did, 'lbd_bool', int64(1)); end
                H5D.close(did);
            end
            H5G.close(gid);

            % integer / logical points never measured (stopped early)
            masks = vn(cellfun(@(k) ~isempty(obj.Values.(k).Measured) && ~all(obj.Values.(k).Measured(:)), vn));
            if ~isempty(masks)
                gid = H5G.create(fid, 'measured', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
                for i = 1:numel(masks)
                    val = obj.Values.(masks{i});
                    did = lbd_write_dataset(gid, val.Name, uint8(lbd.Dataset.whole(val.Measured)), ...
                        numel(val.Dims) + numel(val.PointShape), compression);
                    H5D.close(did);
                end
                H5G.close(gid);
            end

            gid = H5G.create(fid, 'meta', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
            lbd_write_meta(gid, obj.Meta, "meta");
            H5G.close(gid);

            if ~isempty(obj.Plot) || ~isempty(obj.Style) || ~isempty(obj.StyleName)
                gid = H5G.create(fid, 'plot', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
                if ~isempty(obj.Plot), lbd_write_attr(gid, 'spec', lbd_to_json(obj.Plot, "Plot")); end
                if ~isempty(obj.Style), lbd_write_attr(gid, 'style', lbd_to_json(obj.Style, "Style")); end
                if ~isempty(obj.StyleName), lbd_write_attr(gid, 'style_name', obj.StyleName); end
                if ~isempty(obj.Matplotlib) && strlength(obj.Matplotlib) > 0
                    lbd_write_attr(gid, 'matplotlib', obj.Matplotlib);
                end
                H5G.close(gid);
            end
            obj.Created = created;
            obj.Writer = writer;
            obj.LbdVersion = ver;
        end
    end

    methods (Static, Hidden)
        function id = newIdText()
            %NEWIDTEXT  A new identity text (for tests).
            id = lbd_uuid7();
        end

        function id = readId(fid, name, base)
            %READID  An identity attribute ('id', 'parent_id'): empty when missing; a value that
            %   isn't a UUID is reported (warning lbd:badId) and treated as missing.
            id = string(lbd_attr_or(fid, name, string.empty));
            if isempty(id) || strlength(id) == 0
                id = string.empty;
            elseif isempty(regexp(id, '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$', 'once'))
                warning('lbd:badId', '%s: its %s "%s" is not a UUID; it is ignored', base, name, id);
                id = string.empty;
            else
                id = lower(id);
            end
        end

        function same = samePath(a, b)
            %SAMEPATH  Whether two paths name the same file (full paths; case-insensitive on Windows).
            fa = string(java.io.File(char(a)).getCanonicalPath());
            fb = string(java.io.File(char(b)).getCanonicalPath());
            if ispc
                same = strcmpi(fa, fb);
            else
                same = fa == fb;
            end
        end

        function d = fromFile(path, loadAll, names)
            %FROMFILE  Used by lbd.load / lbd.info. With loadAll=false, only the values in
            %   NAMES (string array, may be empty) get their data read.
            path = string(path);
            if ~isfile(path)
                error('lbd:notFound', 'file not found: %s', path);
            end
            [~, fname, fext] = fileparts(path);
            base = fname + fext;
            writing = lower(fext) == ".writing";
            if ~writing
                d = lbd.Dataset.readFile(path, loadAll, names, false, base);
                return
            end
            warning('lbd:writing', ['%s is still being written, or its writer stopped before finishing ' ...
                '(lbd.writingStatus tells which); reading what was written so far'], base);
            % A file being written can be caught while its writer finishes it (the description
            % and metadata are rewritten then): read it again a moment later.
            for attempt = 1:20
                try
                    d = lbd.Dataset.readFile(path, loadAll, names, true, base);
                    return
                catch err
                    if attempt == 20 || err.identifier == "lbd:notFound", rethrow(err); end
                    if ~isfile(path)
                        error('lbd:notFound', '%s was finished while it was read: open %s', base, ...
                            extractBefore(base, strlength(base) - strlength(".writing") + 1));
                    end
                    pause(0.05);
                end
            end
        end

        function d = readFile(path, loadAll, names, writing, base)
            %READFILE  One reading of the file (see fromFile).
            if writing
                fid = lbd_own_writers("get", path);   % written by this MATLAB: one HDF5 handle per file
                if isempty(fid)
                    fid = lbd_open_writing(path);
                    closer = onCleanup(@() H5F.close(fid));
                end
            else
                fid = H5F.open(path, 'H5F_ACC_RDONLY', 'H5P_DEFAULT');
                closer = onCleanup(@() H5F.close(fid));
            end

            if lbd_attr_or(fid, 'lbd_format', "") ~= "LBD"
                error('lbd:invalid', '%s is not an LBD file (missing lbd_format="LBD")', base);
            end
            ver = string(lbd_attr_or(fid, 'lbd_version', ""));
            lbd_check_version(ver, base);

            d = lbd.Dataset(lbd_attr_or(fid, 'title', ""), lbd_attr_or(fid, 'description', ""));
            d.Created = lbd_attr_or(fid, 'created', string.empty);
            d.Writer = lbd_attr_or(fid, 'writer', string.empty);
            d.LbdVersion = ver;
            d.Path = path;
            d.Id = lbd.Dataset.readId(fid, 'id', base);
            d.ParentId = lbd.Dataset.readId(fid, 'parent_id', base);

            if H5L.exists(fid, 'meta', 'H5P_DEFAULT')
                gid = H5G.open(fid, 'meta');
                d.Meta = lbd_read_meta(gid);
                H5G.close(gid);
            end
            if H5L.exists(fid, 'plot', 'H5P_DEFAULT')
                gid = H5G.open(fid, 'plot');
                d.Plot = lbd_from_json(lbd_attr_or(gid, 'spec', ""), base, 'spec');
                d.Style = lbd_from_json(lbd_attr_or(gid, 'style', ""), base, 'style');
                d.StyleName = lbd_attr_or(gid, 'style_name', string.empty);
                if d.StyleName == "", d.StyleName = string.empty; end
                d.Matplotlib = lbd_attr_or(gid, 'matplotlib', string.empty);
                if d.Matplotlib == "", d.Matplotlib = string.empty; end
                H5G.close(gid);
            end

            if H5L.exists(fid, 'axes', 'H5P_DEFAULT')
                gid = H5G.open(fid, 'axes');
                for name = lbd_link_names(gid)
                    oid = H5O.open(gid, char(name), 'H5P_DEFAULT');
                    isGroup = H5I.get_type(oid) == H5ML.get_constant_value('H5I_GROUP');
                    H5O.close(oid);
                    if isGroup
                        d.readGroup(gid, name, base);
                        continue
                    end
                    did = H5D.open(gid, char(name));
                    data = lbd_read_dataset(did);
                    elements = lbd_attr_or(did, 'elements', string.empty);
                    if ~isempty(elements) && (~isstring(elements) || numel(elements) ~= numel(data))
                        warning('lbd:badElements', ['%s: axis "%s" has elements that aren''t one text per ' ...
                            'position; they are ignored'], base, name);
                        elements = string.empty;
                    end
                    role = string(lbd_attr_or(did, 'role', ""));
                    if strlength(role) > 0 && role ~= "point"
                        warning('lbd:badRole', '%s: axis "%s" has an unknown role "%s"; it is read as a sweep axis', ...
                            base, name, role);
                        role = "";
                    end
                    a = lbd.Dataset.axisStruct(name, data(:), lbd_attr_or(did, 'unit', ""), ...
                        lbd_attr_or(did, 'label', name), reshape(string(elements), 1, []), "", []);
                    a.Role = role;
                    d.Axes.(name) = a;
                    H5D.close(did);
                end
                H5G.close(gid);
            end

            found = string.empty;
            if H5L.exists(fid, 'values', 'H5P_DEFAULT')
                gid = H5G.open(fid, 'values');
                for name = lbd_link_names(gid)
                    did = H5D.open(gid, char(name));
                    [shape, dtype] = lbd_describe_dataset(did);
                    data = [];
                    if loadAll || any(names == name)
                        data = lbd_read_dataset(did);
                        if dtype == "bool", data = logical(data); end
                    end
                    d.Values.(name) = struct('Name', name, 'Data', data, ...
                        'Axes', lbd.Dataset.axesList(lbd_attr_or(did, 'axes', "")), 'Dims', {{}}, ...
                        'Unit', lbd_attr_or(did, 'unit', ""), 'Label', lbd_attr_or(did, 'label', name), ...
                        'Shape', shape, 'Dtype', dtype, 'PointShape', zeros(1, 0), 'Elements', {{}}, ...
                        'Measured', []);
                    found(end+1) = name; %#ok<AGROW>
                    H5D.close(did);
                end
                H5G.close(gid);
            end
            if H5L.exists(fid, 'measured', 'H5P_DEFAULT')
                gid = H5G.open(fid, 'measured');
                for name = lbd_link_names(gid)
                    if ~isfield(d.Values, name) || isempty(d.Values.(name).Data), continue; end
                    did = H5D.open(gid, char(name));
                    m = logical(lbd_read_dataset(did));
                    H5D.close(did);
                    v = d.Values.(name);
                    if writing
                        m = lbd.Dataset.cutTo(m, size(v.Data));
                    end
                    if isequal(size(m), size(v.Data))
                        v.Measured = m;
                        d.Values.(name) = v;
                    else
                        warning('lbd:badMask', '%s: the measured mask of "%s" has size %s, not %s; it is ignored', ...
                            base, name, mat2str(size(m)), mat2str(size(v.Data)));
                    end
                end
                H5G.close(gid);
            end
            d.resolveDims(base);
            if writing                 % a growing axis, a group's levels and their values may be caught mid-write
                d.sameLengths();
            end
            if ~loadAll && ~isempty(names)
                missing = setdiff(names, found);
                if ~isempty(missing)
                    error('lbd:notFound', '%s: no value(s) named %s', base, strjoin(missing, ", "));
                end
            end
            d.validateLoaded();
        end

        function [data, measured] = notMeasured(shape, kind, name, live)
            %NOTMEASURED  A value of SHAPE where nothing is measured yet: NaN, or 0 with a false
            %   mask for integers and logicals. LIVE: no data at all (lbd.Writer keeps it in the file).
            sz = [shape ones(1, max(0, 2 - numel(shape)))];
            if numel(shape) == 1, sz = [shape 1]; end
            if live, sz = [0 0]; end
            measured = [];
            switch kind
                case "float64", data = nan(sz);
                case "float32", data = nan(sz, 'single');
                case "complex128", data = complex(nan(sz), nan(sz));
                case "complex64", data = complex(nan(sz, 'single'), nan(sz, 'single'));
                case "bool", data = false(sz); measured = false(sz);
                case {"int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64"}
                    data = zeros(sz, char(kind)); measured = false(sz);
                otherwise
                    error('lbd:invalid', 'value "%s": unsupported Dtype "%s"', name, kind);
            end
            if live, measured = []; end
        end

        function x = cutTo(x, sz)
            %CUTTO  The first SZ(k) entries along each dimension (a file being written).
            idx = arrayfun(@(k) 1:min(size(x, k), sz(k)), 1:numel(sz), 'UniformOutput', false);
            x = x(idx{:});
        end

        function list = axesList(axes)
            if isempty(axes)
                list = strings(1, 0);
            elseif ischar(axes) || (isstring(axes) && isscalar(axes))
                if strlength(string(axes)) == 0
                    list = strings(1, 0);
                else
                    list = strtrim(split(string(axes), ","))';
                end
            else
                list = string(axes(:))';
            end
        end

        function data = coerce(data, dtype, name)
            if ~(isnumeric(data) || islogical(data))
                error('lbd:invalid', 'value "%s" must be numeric or logical, got %s', name, class(data));
            end
            switch dtype
                case "auto"
                    return
                case "float64", data = lbd.Dataset.realOnly(data, dtype, name); data = double(data);
                case "float32", data = lbd.Dataset.realOnly(data, dtype, name); data = single(data);
                case "complex128", data = complex(double(data));
                case "complex64", data = complex(single(data));
                case "bool", data = lbd.Dataset.realOnly(data, dtype, name); data = logical(data);
                case {"int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64"}
                    data = lbd.Dataset.realOnly(data, dtype, name);
                    data = cast(data, char(dtype));
                otherwise
                    error('lbd:invalid', 'value "%s": unsupported Dtype "%s"', name, dtype);
            end
        end

        function elements = checkElements(elements, n, where)
            %CHECKELEMENTS  A row of texts, one per position (N of them, if N isn't empty).
            if isempty(elements)
                elements = string.empty;
                return
            end
            if iscellstr(elements) || ischar(elements), elements = string(elements); end
            if ~isstring(elements)
                error('lbd:invalid', '%s: Elements must be texts, one per position, not %s', where, class(elements));
            end
            elements = reshape(elements, 1, []);
            if ~isempty(n) && numel(elements) ~= n
                error('lbd:invalid', '%s: %d elements for %d positions; give one text per position', ...
                    where, numel(elements), n);
            end
        end

        function named = valueElements(elements, point, name)
            %VALUEELEMENTS  Each data point dimension's texts (string.empty: numbered).
            where = sprintf('value "%s"', name);
            named = repmat({string.empty}, 1, numel(point));
            if isempty(elements), return; end
            if isempty(point)
                error('lbd:invalid', ['%s: Elements name the positions in a data point; give Shape too ' ...
                    '(each data point here is one number)'], where);
            end
            if ~iscell(elements)
                if numel(point) ~= 1
                    error('lbd:invalid', ['%s: give one list of elements per dimension of a data point ' ...
                        '(%d for Shape=%s), as a cell; [] for a dimension left numbered'], where, numel(point), mat2str(point));
                end
                elements = {elements};
            end
            if numel(elements) ~= numel(point)
                error('lbd:invalid', ['%s: give one list of elements per dimension of a data point ' ...
                    '(%d for Shape=%s); [] for a dimension left numbered'], where, numel(point), mat2str(point));
            end
            for k = 1:numel(point)
                named{k} = lbd.Dataset.checkElements(elements{k}, point(k), ...
                    string(where) + ", dimension " + k + " of a data point");
            end
        end

        function data = realOnly(data, dtype, name)
            if ~isreal(data)
                error('lbd:invalid', 'value "%s" is complex; refusing to drop the imaginary part (Dtype="%s")', name, dtype);
            end
        end
    end

    methods (Hidden)
        function plan = planWrite(obj, args)
            %PLANWRITE  Check a write against the dataset's shapes; returns what to put where
            %   (lbd.Writer uses the same plan). Nothing is changed.
            if mod(numel(args), 2) ~= 0
                error('lbd:invalid', 'write: give each name followed by its position or data, e.g. write(power=3, S21=trace)');
            end
            names = strings(1, numel(args) / 2);
            for k = 1:numel(names)
                n = args{2*k - 1};
                if ~(ischar(n) || (isstring(n) && isscalar(n)))
                    error('lbd:invalid', 'write: names must be texts, e.g. write("power", 3, "S21", trace)');
                end
                names(k) = string(n);
            end
            given = args(2:2:end);
            if numel(unique(names)) < numel(names)
                [u, ~, j] = unique(names);
                error('lbd:invalid', 'write: "%s" is given twice', u(find(accumarray(j(:), 1) > 1, 1)));
            end
            parent = [];
            k = find(names == "Parent");
            if ~isempty(k) && ~isfield(obj.Axes, "Parent") && ~isfield(obj.Values, "Parent")
                parent = given{k};
                names(k) = [];
                given(k) = [];
                if isempty(parent)
                    error('lbd:invalid', 'write: Parent= takes the index that write returned');
                end
            end
            isAxis = arrayfun(@(n) isfield(obj.Axes, n), names);
            isValue = arrayfun(@(n) isfield(obj.Values, n), names);
            if any(~isAxis & ~isValue)
                error('lbd:invalid', 'write: no axis or value named %s; axes: %s; values: %s', ...
                    strjoin(names(~isAxis & ~isValue), ", "), strjoin(string(fieldnames(obj.Axes)), ", "), ...
                    strjoin(string(fieldnames(obj.Values)), ", "));
            end
            inGroup = isAxis & arrayfun(@(n) isfield(obj.Axes, n) && strlength(obj.Axes.(n).Group) > 0, names);
            if ~any(isValue) && ~any(inGroup)
                error('lbd:invalid', 'write: give at least one value with its data, e.g. write(power=3, S21=trace)');
            end
            if ~isempty(parent) && ~any(inGroup)
                error('lbd:invalid', ['write: Parent= names an outer point of a group; give the next axes of that ' ...
                    'group with it, e.g. write(Parent=i, B=25, f=x)']);
            end
            points = struct();
            if any(inGroup)
                points = obj.planPoints(names(inGroup), given(inGroup), parent);
            end
            pos = struct();
            grow = [];
            for k = find(isAxis & ~inGroup)
                a = names(k);
                if obj.Axes.(a).Grows
                    if ~isempty(grow)
                        error('lbd:invalid', 'write: one growing axis at a time, not "%s" and "%s"', grow.axis, a);
                    end
                    c = given{k};
                    if ~(isnumeric(c) && isreal(c) && (isscalar(c) || isvector(c)) && all(isfinite(double(c(:)))))
                        error('lbd:invalid', 'write: "%s" takes a coordinate or a vector of them, finite numbers', a);
                    end
                    grow = struct('axis', a, 'coords', double(c(:)), 'scalar', isscalar(c));
                else
                    pos.(a) = obj.position(a, given{k});
                end
            end
            puts = {};
            for k = find(isValue)
                name = names(k);
                v = obj.Values.(name);
                for a = names(isAxis)
                    if ~any(v.Axes == a)
                        error('lbd:invalid', 'write: "%s" doesn''t lie on "%s" (its axes: %s)', name, a, strjoin(v.Axes, ", "));
                    end
                end
                idx = cell(1, numel(v.Dims) + numel(v.PointShape));
                need = zeros(1, 0);
                free = strings(1, 0);
                for i = 1:numel(v.Dims)
                    dm = v.Dims{i};
                    a = dm(1);
                    ax = obj.Axes.(a);
                    if obj.isGroupDim(dm)
                        g = ax.Group;
                        if ~isfield(points, g)              % every point of the level
                            idx{i} = ':';
                            need(end+1) = obj.dimLength(dm); %#ok<AGROW>
                            free(end+1) = strjoin(dm, ","); %#ok<AGROW>
                            continue
                        end
                        p = points.(g);
                        if p.depth ~= dm(end)
                            missing = dm(find(dm == p.depth) + 1:end);
                            error('lbd:invalid', 'write: "%s" lies on the points of %s: give %s too', ...
                                name, strjoin(dm, ", "), strjoin(missing, ", "));
                        end
                        idx{i} = p.index;
                        if ~isempty(p.n)
                            need(end+1) = p.n; %#ok<AGROW>
                            free(end+1) = strjoin(dm, ","); %#ok<AGROW>
                        end
                    elseif ax.Grows
                        if isempty(grow) || grow.axis ~= a
                            error('lbd:invalid', ['write: "%s" lies on the growing axis "%s": give its coordinate ' ...
                                '(%s=...), which adds a point'], name, a, a);
                        end
                        start = numel(ax.Data);
                        if grow.scalar
                            idx{i} = start + 1;
                        else
                            idx{i} = start + (1:numel(grow.coords));
                            need(end+1) = numel(grow.coords); %#ok<AGROW>
                            free(end+1) = a; %#ok<AGROW>
                        end
                    elseif isfield(pos, a)
                        idx{i} = pos.(a);
                    else
                        idx{i} = ':';
                        need(end+1) = numel(ax.Data); %#ok<AGROW>
                        free(end+1) = a; %#ok<AGROW>
                    end
                end
                for i = 1:numel(v.PointShape)                 % a data point is always given whole
                    idx{numel(v.Dims) + i} = ':';
                    need(end+1) = v.PointShape(i); %#ok<AGROW>
                    free(end+1) = "data point dimension " + i; %#ok<AGROW>
                end
                data = lbd.Dataset.fitsType(given{k}, v.Dtype, name);
                data = lbd.Dataset.shapedFor(data, need, name, free);
                puts{end+1} = struct('name', name, 'idx', {idx}, 'data', data); %#ok<AGROW>
            end
            levels = {};
            result = [];
            gs = string(fieldnames(points))';
            for g = gs
                levels = [levels points.(g).new]; %#ok<AGROW>
            end
            if isscalar(gs)
                result = points.(gs).index;
            elseif ~isempty(gs)
                result = struct();
                for g = gs, result.(g) = points.(g).index; end
            end
            plan = struct('grow', grow, 'levels', {levels}, 'puts', {puts}, 'result', result);
        end

        function pts = planPoints(obj, names, vals, parent)
            %PLANPOINTS  The points a write names in each group: found by their coordinates (the
            %   same coordinates are the same point), or new. Nothing is changed.
            byGroup = struct();
            for k = 1:numel(names)
                g = obj.Axes.(names(k)).Group;
                if ~isfield(byGroup, g), byGroup.(g) = struct('names', strings(1, 0), 'vals', {{}}); end
                byGroup.(g).names(end+1) = names(k);
                byGroup.(g).vals{end+1} = vals{k};
            end
            gs = string(fieldnames(byGroup))';
            if ~isempty(parent) && numel(gs) ~= 1
                error('lbd:invalid', 'write: Parent= names a point of one group; give the axes of that group (and only one group) with it');
            end
            pts = struct();
            for g = gs
                order = obj.Groups.(g).Order;
                given = byGroup.(g);
                ks = sort(arrayfun(@(a) find(order == a), given.names));
                s = ks(1);
                e = ks(end);
                if ~isequal(ks, s:e)
                    error('lbd:invalid', 'write: group "%s" (order %s) needs its axes one after the other; %s missing', ...
                        g, strjoin(order, ", "), strjoin(setdiff(order(s:e), given.names, 'stable'), ", "));
                end
                if isempty(parent) && s > 1
                    error('lbd:invalid', 'write: "%s" means something only under %s: give %s too, or the outer point with Parent=', ...
                        order(s), strjoin(order(1:s-1), ", "), strjoin(order(1:s-1), ", "));
                end
                if ~isempty(parent) && s == 1
                    error('lbd:invalid', 'write: Parent= names a point of the level above "%s", which is the first axis of group "%s"; leave Parent= out', order(1), g);
                end
                cols = cell(1, e - s + 1);
                lens = zeros(1, 0);
                for m = s:e
                    c = given.vals{given.names == order(m)};
                    if ~(isnumeric(c) && isreal(c) && (isempty(c) || isvector(c)))
                        error('lbd:invalid', 'write: "%s" is an axis of a group: give its coordinate (a number) or a vector of them', order(m));
                    end
                    if any(~isfinite(double(c(:))))
                        error('lbd:invalid', 'write: "%s" got NaN or Inf; coordinates must be finite numbers', order(m));
                    end
                    cols{m - s + 1} = double(c(:)) + 0;          % +0: -0 is the point 0
                    if ~isscalar(c), lens(end+1) = numel(c); end %#ok<AGROW>
                end
                pars = [];
                if ~isempty(parent)
                    nAbove = numel(obj.Axes.(order(s - 1)).Data);
                    if ~(isnumeric(parent) && isreal(parent) && isvector(parent) && all(parent(:) == round(parent(:))))
                        error('lbd:invalid', 'write: Parent= takes the index (or a vector of indices) that write returned');
                    end
                    if any(parent(:) < 1 | parent(:) > nAbove)
                        error('lbd:invalid', 'write: Parent=%s is not a point of "%s" (it has %d: 1 ... %d)', ...
                            mat2str(parent), order(s - 1), nAbove, nAbove);
                    end
                    pars = double(parent(:));
                    if ~isscalar(parent), lens(end+1) = numel(parent); end %#ok<AGROW>
                end
                lens = unique(lens);
                if numel(lens) > 1
                    error('lbd:invalid', 'write: the coordinates given for group "%s" have different lengths %s', g, mat2str(lens));
                end
                many = ~isempty(lens);
                n = 1;
                if many, n = lens; end
                for m = 1:numel(cols)
                    if isscalar(cols{m}), cols{m} = repmat(cols{m}, n, 1); end
                end
                if isempty(pars), pars = zeros(n, 1); elseif isscalar(pars), pars = repmat(pars, n, 1); end
                newCoords = repmat({zeros(0, 1)}, 1, numel(cols));
                newParents = repmat({zeros(0, 1)}, 1, numel(cols));
                pending = containers.Map('KeyType', 'char', 'ValueType', 'double');
                result = zeros(n, 1);
                for i = 1:n
                    p = pars(i);
                    for m = 1:numel(cols)
                        a = order(s + m - 1);
                        c = cols{m}(i);
                        key = sprintf('%d|%d|%.17g', m, p, c);
                        if isKey(pending, key)
                            idx = pending(key);
                        else
                            idx = obj.findPoint(a, p, c);
                            if isempty(idx)
                                idx = numel(obj.Axes.(a).Data) + numel(newCoords{m}) + 1;
                                newCoords{m}(end+1, 1) = c;
                                newParents{m}(end+1, 1) = p;
                                pending(key) = idx;
                            end
                        end
                        p = idx;
                    end
                    result(i) = p;
                end
                new = {};
                for m = 1:numel(cols)
                    if isempty(newCoords{m}), continue; end
                    a = order(s + m - 1);
                    if isempty(obj.Axes.(a).Parent) && s + m - 1 == 1
                        new{end+1} = {a, newCoords{m}, []}; %#ok<AGROW>
                    else
                        new{end+1} = {a, newCoords{m}, newParents{m}}; %#ok<AGROW>
                    end
                end
                if many, index = result; nOut = n; else, index = result(1); nOut = []; end
                pts.(g) = struct('depth', order(e), 'index', index, 'n', nOut, 'new', {new});
            end
            withMany = 0;
            for g = gs, withMany = withMany + ~isempty(pts.(g).n); end
            if withMany > 1
                error('lbd:invalid', 'write: give several points of one group at a time (one point of each other group)');
            end
        end

        function idx = findPoint(obj, a, p, c)
            %FINDPOINT  The index of the point of level A with parent P and coordinate C, or [].
            lk = obj.lookup(a);
            key = sprintf('%d|%.17g', p, c);
            idx = [];
            if isKey(lk.map, key), idx = lk.map(key); end
        end

        function lk = lookup(obj, a)
            %LOOKUP  Level A's points by (parent, coordinate); rebuilt when the level changed by hand.
            ax = obj.Axes.(a);
            n = numel(ax.Data);
            if isfield(obj.Lookups, a) && obj.Lookups.(a).n == n
                lk = obj.Lookups.(a);
                return
            end
            map = containers.Map('KeyType', 'char', 'ValueType', 'double');
            if n > 0
                parents = zeros(n, 1);
                if ~isempty(ax.Parent), parents = double(ax.Parent(:)); end
                keys = compose("%d|%.17g", parents, double(ax.Data(:)) + 0);
                [u, first] = unique(keys, 'stable');
                map = containers.Map(cellstr(u), num2cell(first(:)'));
            end
            lk = struct('n', n, 'map', map);
            obj.Lookups.(a) = lk;
        end

        function i = position(obj, a, x)
            %POSITION  An index of a fixed axis (1 = its first point), from an index or an element.
            ax = obj.Axes.(a);
            n = numel(ax.Data);
            if ischar(x) || (isstring(x) && isscalar(x))
                i = find(ax.Elements == string(x), 1);
                if isempty(i)
                    if isempty(ax.Elements)
                        error('lbd:invalid', 'write: "%s" has no element "%s"; give an index (1 ... %d)', a, x, n);
                    end
                    error('lbd:invalid', 'write: "%s" has no element "%s"; its elements: %s', a, x, strjoin(ax.Elements, ", "));
                end
            elseif isnumeric(x) && isscalar(x) && isreal(x) && x == round(x)
                if x < 1 || x > n
                    error('lbd:invalid', 'write: index %d is out of range for "%s" (it has %d points: 1 ... %d)', x, a, n, n);
                end
                i = double(x);
            else
                error('lbd:invalid', 'write: "%s" takes one position: an index (1 ... %d) or one of its elements', a, n);
            end
        end

        function applyWrite(obj, plan)
            if ~isempty(plan.grow)
                g = plan.grow.axis;
                c = plan.grow.coords;
                obj.Axes.(g).Data = [double(obj.Axes.(g).Data); c];
                obj.extendValues(g, numel(c));
            end
            obj.growLevels(plan);
            for k = 1:numel(plan.levels)
                obj.extendValues(plan.levels{k}{1}, numel(plan.levels{k}{2}));
            end
            for k = 1:numel(plan.puts)
                p = plan.puts{k};
                v = obj.Values.(p.name);
                if isempty(p.idx)
                    v.Data = p.data;
                    if ~isempty(v.Measured), v.Measured = true; end
                else
                    v.Data(p.idx{:}) = p.data;
                    if ~isempty(v.Measured), v.Measured(p.idx{:}) = true; end
                end
                if ~isa(v.Data, 'lbd.OnDisk') && startsWith(v.Dtype, "complex") && isreal(v.Data)
                    v.Data = complex(v.Data);       % MATLAB drops an all-zero imaginary part
                end
                obj.Values.(p.name) = v;
            end
        end

        function growLevels(obj, plan)
            %GROWLEVELS  Add a write's new group points to their levels (coordinates, parents,
            %   lookups); warn about a new point that differs from one there only by rounding.
            near = strings(1, 0);
            for k = 1:numel(plan.levels)
                a = plan.levels{k}{1};
                c = plan.levels{k}{2};
                p = plan.levels{k}{3};
                ax = obj.Axes.(a);
                start = numel(ax.Data);
                lk = [];
                if isfield(obj.Lookups, a) && obj.Lookups.(a).n == start, lk = obj.Lookups.(a); end
                all = [double(ax.Data(:)); c];
                if any(all ~= round(all))                    % integers are never near-equal
                    scale = max([max(all) - min(all), abs(min(all)), abs(max(all))]);
                    if isempty(p), parents = zeros(size(c)); old = zeros(start, 1); else, parents = p; old = double(ax.Parent(:)); end
                    for q = unique(parents)'
                        s = unique([double(ax.Data(old == q)); c(parents == q)]);
                        close = find(diff(s) <= 1e-9 * scale, 1);
                        if ~isempty(close)
                            near(end+1) = sprintf('%s = %.17g is a new point next to %.17g', a, s(close + 1), s(close)); %#ok<AGROW>
                        end
                    end
                end
                ax.Data = all;
                if ~isempty(p), ax.Parent = [ax.Parent(:); int64(p)]; end
                obj.Axes.(a) = ax;
                if ~isempty(lk)
                    if isempty(p), pp = zeros(size(c)); else, pp = p; end
                    for i = 1:numel(c)
                        lk.map(sprintf('%d|%.17g', pp(i), c(i))) = start + i;
                    end
                    lk.n = start + numel(c);
                    obj.Lookups.(a) = lk;
                end
            end
            if ~isempty(near)
                warning('lbd:nearEqual', ['write: %s. Coordinates are compared exactly: round the coordinate, or ' ...
                    'write with Parent= (the index write returned)'], strjoin(near(1:min(3, end)), "; "));
            end
        end

        function extendValues(obj, axis, k)
            %EXTENDVALUES  K points were added to AXIS (a growing axis, or a group's level): every
            %   value on it grows along that dimension, the new points not measured.
            for name = string(fieldnames(obj.Values))'
                v = obj.Values.(name);
                for pos = 1:numel(v.Dims)
                    if v.Dims{pos}(end) ~= axis, continue; end
                    sz = size(v.Data, 1:max(ndims(v.Data), pos));
                    sz(pos) = k;
                    if ~isfloat(v.Data) && isempty(v.Measured)
                        v.Measured = true(size(v.Data));
                    end
                    v.Data = cat(pos, v.Data, lbd.Dataset.fillLike(v.Data, sz));
                    if ~isempty(v.Measured)
                        v.Measured = cat(pos, v.Measured, false(sz));
                    end
                    v.Shape(pos) = v.Shape(pos) + k;
                end
                obj.Values.(name) = v;
            end
        end

        function sameLengths(obj)
            %SAMELENGTHS  In a file being written, keep what is complete: each group level's
            %   points up to the first whose parent isn't there yet, and each axis (or level) and
            %   the values along it cut to the length all of them have reached.
            changed = true;
            while changed
                changed = false;
                for g = string(fieldnames(obj.Groups))'
                    above = Inf;
                    for k = 1:numel(obj.Groups.(g).Order)
                        a = obj.Groups.(g).Order(k);
                        ax = obj.Axes.(a);
                        n = numel(ax.Data);
                        if k > 1
                            n = min(n, numel(ax.Parent));
                            late = find(ax.Parent(1:n) > above, 1);
                            if ~isempty(late), n = late - 1; end
                        end
                        if n < numel(ax.Data) || (k > 1 && n < numel(ax.Parent))
                            ax.Data = ax.Data(1:n);
                            if k > 1, ax.Parent = ax.Parent(1:n); end
                            obj.Axes.(a) = ax;
                            changed = true;
                        end
                        above = n;
                    end
                end
                vn = string(fieldnames(obj.Values))';
                for a = string(fieldnames(obj.Axes))'
                    n = numel(obj.Axes.(a).Data);
                    for name = vn
                        v = obj.Values.(name);
                        for i = 1:min(numel(v.Dims), numel(v.Shape))
                            if v.Dims{i}(end) == a, n = min(n, v.Shape(i)); end
                        end
                    end
                    if n < numel(obj.Axes.(a).Data)
                        obj.Axes.(a).Data = obj.Axes.(a).Data(1:n);
                        if ~isempty(obj.Axes.(a).Parent), obj.Axes.(a).Parent = obj.Axes.(a).Parent(1:n); end
                        changed = true;
                    end
                    for name = vn
                        v = obj.Values.(name);
                        cut = false;
                        for i = 1:min(numel(v.Dims), numel(v.Shape))
                            if v.Dims{i}(end) == a && v.Shape(i) > n
                                v.Shape(i) = n;
                                cut = true;
                            end
                        end
                        if ~cut, continue; end
                        sz = v.Shape;
                        if numel(sz) == 1, sz = [sz 1]; end
                        if ~isempty(v.Data), v.Data = lbd.Dataset.cutTo(v.Data, sz); end
                        if ~isempty(v.Measured), v.Measured = lbd.Dataset.cutTo(v.Measured, sz); end
                        obj.Values.(name) = v;
                    end
                end
            end
        end

        function dims = parseDims(obj, names, where)
            %PARSEDIMS  A value's dimensions from its axis names: a fixed axis is one dimension;
            %   consecutive axes of one group, from its first, are one (a level); a group's name
            %   means all its axes.
            dims = {};
            seen = strings(1, 0);
            i = 1;
            while i <= numel(names)
                name = names(i);
                if isfield(obj.Groups, name)
                    order = obj.Groups.(name).Order;
                    if isempty(order)
                        error('lbd:invalid', '%s: group "%s" has no axes yet; add them with addAxis(..., Group="%s")', where, name, name);
                    end
                    dm = order;
                    owner = name;
                    i = i + 1;
                elseif isfield(obj.Axes, name) && strlength(obj.Axes.(name).Group) > 0
                    owner = obj.Axes.(name).Group;
                    order = obj.Groups.(owner).Order;
                    if name ~= order(1)
                        k = find(order == name);
                        error('lbd:invalid', ['%s: "%s" is an inner axis of group "%s" (order %s); a value lies on an ' ...
                            'outer part of a group: give %s, not "%s" alone'], where, name, owner, strjoin(order, ", "), ...
                            strjoin(order(1:k), ", "), name);
                    end
                    k = 1;
                    while i + k <= numel(names) && k < numel(order) && names(i + k) == order(k + 1)
                        k = k + 1;
                    end
                    if i + k <= numel(names) && any(order == names(i + k))
                        error('lbd:invalid', '%s: the axes of group "%s" must be given in its order (%s), one after the other from "%s"', ...
                            where, owner, strjoin(order, ", "), order(1));
                    end
                    dm = order(1:k);
                    i = i + k;
                else
                    if ~isfield(obj.Axes, name)
                        error('lbd:invalid', '%s: axis "%s" does not exist; add it with addAxis first', where, name);
                    end
                    dm = name;
                    owner = name;
                    i = i + 1;
                end
                if any(seen == owner)
                    error('lbd:invalid', '%s: "%s" appears more than once in %s', where, owner, strjoin(names, ", "));
                end
                seen(end+1) = owner; %#ok<AGROW>
                dims{end+1} = dm; %#ok<AGROW>
            end
        end

        function n = dimLength(obj, dm)
            %DIMLENGTH  A dimension's length: its axis's points, or its level's.
            n = numel(obj.Axes.(dm(end)).Data);
        end

        function tf = isGroupDim(obj, dm)
            tf = strlength(obj.Axes.(dm(1)).Group) > 0;
        end

        function out = ancestors(obj, dm)
            %ANCESTORS  For each point of the level DM ends at, its point at every level of DM
            %   (outer first; the last is 1 ... n).
            idx = (1:obj.dimLength(dm))';
            out = cell(1, numel(dm));
            out{end} = idx;
            for m = numel(dm):-1:2
                idx = double(obj.Axes.(dm(m)).Parent(idx));
                idx = idx(:);
                out{m - 1} = idx;
            end
        end

        function v = valueNamed(obj, name)
            if ~isfield(obj.Values, name)
                error('lbd:notFound', 'no value named "%s"; values: %s', name, strjoin(string(fieldnames(obj.Values)), ", "));
            end
            v = obj.Values.(name);
        end

        function nd = part(obj, v, pos, sel)
            %PART  A new dataset with the part of V that SEL picks along dimension POS:
            %   {"index", i} of a fixed axis, {"point", p} of a level, or {"under", j, p, pts}:
            %   the points under point p of level j. A copy.
            nd = lbd.Dataset(obj.Title);
            idx = {};
            dims = {};
            for i = 1:numel(v.Dims)
                dm = v.Dims{i};
                if i ~= pos
                    obj.copyDim(nd, dm);
                    idx{end+1} = ':'; %#ok<AGROW>
                    dims{end+1} = dm; %#ok<AGROW>
                    continue
                end
                if sel{1} == "index" || sel{1} == "point"
                    idx{end+1} = sel{2}; %#ok<AGROW>
                    continue
                end
                j = sel{2}; p = sel{3}; pts = sel{4};
                rest = dm(j + 1:end);
                if isscalar(rest)
                    src = obj.Axes.(rest);
                    nd.Axes.(rest) = lbd.Dataset.axisStruct(rest, src.Data(pts), src.Unit, src.Label, string.empty, "", []);
                    idx{end+1} = pts; %#ok<AGROW>
                else
                    g = obj.Axes.(dm(1)).Group;
                    nd.Groups.(g) = struct('Name', g, 'Order', rest);
                    keepAbove = [];
                    for m = j + 1:numel(dm)
                        chain = obj.ancestors(dm(1:m));
                        keep = find(chain{j} == p);
                        src = obj.Axes.(dm(m));
                        parent = [];
                        if ~isempty(keepAbove) || m > j + 1
                            [~, loc] = ismember(double(src.Parent(keep)), keepAbove);
                            parent = int64(loc(:));
                        end
                        nd.Axes.(dm(m)) = lbd.Dataset.axisStruct(dm(m), src.Data(keep), src.Unit, src.Label, string.empty, g, parent);
                        keepAbove = keep;
                    end
                    idx{end+1} = keepAbove; %#ok<AGROW>
                end
                dims{end+1} = rest; %#ok<AGROW>
            end
            idx = [idx repmat({':'}, 1, numel(v.PointShape))];
            shape = [zeros(1, 0) cellfun(@(dm) nd.dimLength(dm), dims) v.PointShape];
            sz = [shape ones(1, max(0, 2 - numel(shape)))];
            if numel(shape) == 1, sz = [shape 1]; end
            data = reshape(lbd.Dataset.pick(v.Data, idx), sz);
            if startsWith(v.Dtype, "complex"), data = complex(data); end
            measured = [];
            if ~isempty(v.Measured), measured = reshape(lbd.Dataset.pick(v.Measured, idx), sz); end
            nd.Values.(v.Name) = struct('Name', v.Name, 'Data', data, 'Axes', [strings(1, 0) dims{:}], 'Dims', {dims}, ...
                'Unit', v.Unit, 'Label', v.Label, 'Shape', shape, 'Dtype', v.Dtype, 'PointShape', v.PointShape, ...
                'Elements', {v.Elements}, 'Measured', measured);
        end

        function copyDim(obj, nd, dm)
            if obj.isGroupDim(dm)
                g = obj.Axes.(dm(1)).Group;
                if ~isfield(nd.Groups, g), nd.Groups.(g) = struct('Name', g, 'Order', dm); end
            end
            for a = dm
                nd.Axes.(a) = obj.Axes.(a);
            end
        end

        function fa = fileAxes(obj)
            %FILEAXES  The axes the file stores at its top: the fixed axes, then each value's
            %   data point dimensions (format 1.2: role "point", 0 ... n-1).
            fa = {};
            for name = string(fieldnames(obj.Axes))'
                if strlength(obj.Axes.(name).Group) == 0, fa{end+1} = obj.Axes.(name); end %#ok<AGROW>
            end
            done = strings(1, 0);
            for name = string(fieldnames(obj.Values))'
                v = obj.Values.(name);
                pn = lbd.Dataset.pointNames(v);
                for k = 1:numel(v.PointShape)
                    if any(done == pn(k)), continue; end
                    done(end+1) = pn(k); %#ok<AGROW>
                    label = v.Label;
                    if numel(v.PointShape) > 1, label = v.Label + " (dim" + k + ")"; end
                    el = string.empty;
                    if k <= numel(v.Elements), el = v.Elements{k}; end
                    a = lbd.Dataset.axisStruct(pn(k), int64(0:v.PointShape(k) - 1)', "", label, el, "", []);
                    a.Role = "point";
                    fa{end+1} = a; %#ok<AGROW>
                end
            end
        end

        function resolveDims(obj, base)
            %RESOLVEDIMS  Each value's axes as the file lists them -> its dimensions: the last
            %   ones with role "point" are its data point's (they leave Axes), the others sweep
            %   dimensions (a fixed axis, or a group's level).
            trailing = strings(1, 0);
            for name = string(fieldnames(obj.Values))'
                v = obj.Values.(name);
                names = v.Axes;
                k = numel(names);
                while k > 0 && isfield(obj.Axes, names(k)) && obj.Axes.(names(k)).Role == "point"
                    k = k - 1;
                end
                trailing = [trailing names(k+1:end)]; %#ok<AGROW>
                try
                    dims = obj.parseDims(names(1:k), sprintf('value "%s"', name));
                catch err
                    error('lbd:invalid', '%s: %s', base, err.message);
                end
                if numel(dims) + numel(names) - k ~= numel(v.Shape)
                    error('lbd:invalid', '%s: value "%s" has %d dimension(s) but axes=%s', base, name, numel(v.Shape), strjoin(names, ","));
                end
                v.Elements = arrayfun(@(a) obj.Axes.(a).Elements, names(k+1:end), 'UniformOutput', false);
                v.Axes = [strings(1, 0) dims{:}];
                v.Dims = dims;
                v.PointShape = v.Shape(numel(dims)+1:end);
                obj.Values.(name) = v;
            end
            for a = string(fieldnames(obj.Axes))'
                if obj.Axes.(a).Role ~= "point", continue; end
                swept = false;
                for name = string(fieldnames(obj.Values))'
                    swept = swept || any(obj.Values.(name).Axes == a);
                end
                if any(trailing == a) && swept
                    error('lbd:invalid', '%s: axis "%s" is a dimension of a data point of some values and a sweep axis of others; it can''t be both', base, a);
                elseif any(trailing == a)
                    obj.Axes = rmfield(obj.Axes, a);
                else
                    obj.Axes.(a).Role = "";
                    warning('lbd:badRole', ['%s: axis "%s" is marked as a dimension of a data point (role "point") but ' ...
                        'no value''s data point uses it; it is read as a sweep axis'], base, a);
                end
            end
        end

        function readGroup(obj, gid, name, base)
            %READGROUP  An axis group (spec 1.8): its axes level by level, each point's parent.
            if isfield(obj.Axes, name)
                error('lbd:invalid', '%s: "%s" is used by an axis and a group', base, name);
            end
            ggid = H5G.open(gid, char(name));
            closer = onCleanup(@() H5G.close(ggid));
            order = lbd.Dataset.axesList(string(lbd_attr_or(ggid, 'order', "")));
            if isempty(order)
                error('lbd:invalid', '%s: the axis group "%s" has no ''order'' attribute; it breaks the LBD format', base, name);
            end
            for k = 1:numel(order)
                a = order(k);
                if isfield(obj.Axes, a) || isfield(obj.Groups, a)
                    error('lbd:invalid', '%s: "%s" (in group "%s") is used twice', base, a, name);
                end
                if ~H5L.exists(ggid, char(a), 'H5P_DEFAULT')
                    error('lbd:invalid', '%s: /axes/%s/%s is missing', base, name, a);
                end
                did = H5D.open(ggid, char(a));
                data = lbd_read_dataset(did);
                ax = lbd.Dataset.axisStruct(a, double(data(:)), lbd_attr_or(did, 'unit', ""), lbd_attr_or(did, 'label', a), ...
                    string.empty, name, []);
                H5D.close(did);
                if k > 1
                    if ~H5L.exists(ggid, char(a + "._parent"), 'H5P_DEFAULT')
                        error('lbd:invalid', '%s: axis "%s" of group "%s" has no "%s._parent"; it breaks the LBD format', base, a, name, a);
                    end
                    did = H5D.open(ggid, char(a + "._parent"));
                    p = lbd_read_dataset(did);
                    H5D.close(did);
                    ax.Parent = int64(p(:)) + 1;                     % from 1 in MATLAB
                end
                obj.Axes.(a) = ax;
            end
            obj.Groups.(name) = struct('Name', name, 'Order', order);
        end

        function appendCoordinates(obj, axis, coords)
            %APPENDCOORDINATES  Points added to a growing axis (lbd.Writer).
            obj.Axes.(axis).Data = [double(obj.Axes.(axis).Data); coords(:)];
        end

        function attachSource(obj, source)
            %ATTACHSOURCE  lbd.open: each value's data (and mask) becomes an lbd.OnDisk.
            obj.Source = source;
            for name = string(fieldnames(obj.Values))'
                v = obj.Values.(name);
                v.Data = lbd.OnDisk(source, "/values/" + name, v.Shape, v.Dtype);
                hasMask = source.run(@(fid) H5L.exists(fid, '/measured', 'H5P_DEFAULT') && ...
                    H5L.exists(fid, char("/measured/" + name), 'H5P_DEFAULT'));
                if hasMask
                    v.Measured = lbd.OnDisk(source, "/measured/" + name, v.Shape, "bool");
                end
                obj.Values.(name) = v;
            end
        end

        function saveInPlace(obj)
            %SAVEINPLACE  The description, metadata and saved view rewritten in the opened file.
            if ~isempty(obj.Plot), lbd_to_json(obj.Plot, "Plot"); end
            if ~isempty(obj.Style), lbd_to_json(obj.Style, "Style"); end
            check = tempname + ".h5";                % metadata that can't be stored: refused before any change
            cfid = H5F.create(check, 'H5F_ACC_TRUNC', 'H5P_DEFAULT', 'H5P_DEFAULT');
            try
                gid = H5G.create(cfid, 'meta', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
                lbd_write_meta(gid, obj.Meta, "meta");
                H5G.close(gid);
                H5F.close(cfid);
                delete(check);
            catch err
                H5F.close(cfid);
                delete(check);
                rethrow(err);
            end
            obj.Source.run(@(fid) rewriteDescription(fid, obj));
        end

        function keepIdentityAt(obj, path)
            %KEEPIDENTITYAT  Saving to PATH keeps the Id (lbd.recover: the same measurement).
            obj.Path = string(path);
        end

        function setIdentity(obj, id, created, writer)
            obj.Id = id;
            obj.Created = created;
            obj.Writer = writer;
        end
    end

    methods (Static, Hidden)
        function x = fitsType(x, dtype, name)
            %FITSTYPE  Data for a value of type DTYPE: complex refused for real values, integers
            %   and logicals only when exactly representable.
            if ~(isnumeric(x) || islogical(x))
                error('lbd:invalid', 'write: "%s" takes numbers, not %s', name, class(x));
            end
            if ~isreal(x) && ~startsWith(dtype, "complex")
                error('lbd:invalid', 'write: "%s" is real (%s); refusing to drop an imaginary part', name, dtype);
            end
            switch dtype
                case "bool"
                    if ~islogical(x) && ~all(x(:) == 0 | x(:) == 1)
                        error('lbd:invalid', 'write: "%s" is logical; give true/false (or 0/1)', name);
                    end
                    x = logical(x);
                case {"int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64"}
                    if ~isinteger(x) && ~islogical(x) && any(~isfinite(x(:)) | x(:) ~= round(x(:)))
                        error('lbd:invalid', 'write: "%s" holds whole numbers (%s)', name, dtype);
                    end
                    if ~isempty(x) && (double(min(x(:))) < double(intmin(dtype)) || double(max(x(:))) > double(intmax(dtype)))
                        error('lbd:invalid', 'write: "%s" (%s) can''t hold %g ... %g', name, dtype, double(min(x(:))), double(max(x(:))));
                    end
                    x = cast(x, char(dtype));
                case "float64", x = double(x);
                case "float32", x = single(x);
                case "complex128", x = complex(double(x));
                case "complex64", x = complex(single(x));
            end
        end

        function x = shapedFor(x, need, name, free)
            %SHAPEDFOR  X arranged as the place it goes: NEED, the sizes of the axes not given.
            if isempty(need)
                ok = isscalar(x);
            elseif isscalar(need)
                ok = isvector(x) && numel(x) == need;
                if ok
                    wasComplex = ~isreal(x);
                    x = reshape(x, [need 1]);
                    if wasComplex, x = complex(x); end
                end
            else
                ok = ndims(x) <= numel(need) && isequal(size(x, 1:numel(need)), need);
            end
            if ~ok
                if isempty(free), what = "one number"; else, what = strjoin(free, ", "); end
                error('lbd:invalid', 'write: "%s" needs data of size %s (%s), not %s', ...
                    name, mat2str([need ones(1, max(0, 1 - numel(need)))]), what, mat2str(size(x)));
            end
        end

        function a = axisStruct(name, data, unit, label, elements, group, parent)
            %AXISSTRUCT  One axis, as Axes holds it.
            a = struct('Name', name, 'Data', data, 'Unit', unit, 'Label', label, 'Elements', elements, ...
                'Role', "", 'Grows', false, 'Group', group, 'Parent', parent);
        end

        function names = pointNames(v)
            %POINTNAMES  The file's names for the dimensions of V's data points.
            names = v.Name + "_dim" + string(1:numel(v.PointShape));
            if isempty(v.PointShape), names = strings(1, 0); end
        end

        function x = pick(data, idx)
            %PICK  DATA at IDX (one entry per dimension; a 1-D value is a column). An lbd.OnDisk
            %   reads only that part.
            x = data(idx{:});
        end

        function x = whole(x)
            %WHOLE  The array itself: an lbd.OnDisk is read whole.
            if isa(x, 'lbd.OnDisk'), x = x.read(); end
        end

        function [t, inv] = ticksOf(c, name, opts)
            %TICKSOF  An axis's ticks (sorted) from its points' coordinates, and each point's tick.
            c = double(c(:));
            if ~isempty(opts.Round), c = round(c, opts.Round); end
            [u, ~, inv] = unique(c);
            if ~isempty(opts.RTol) || ~isempty(opts.ATol)
                r = 0; a = 0;
                if ~isempty(opts.RTol), r = opts.RTol; end
                if ~isempty(opts.ATol), a = opts.ATol; end
                cl = zeros(size(u));
                first = NaN; k = 0;
                for i = 1:numel(u)
                    if isnan(first) || abs(u(i) - first) > a + r * abs(first)
                        first = u(i); k = k + 1;
                    end
                    cl(i) = k;
                end
                t = accumarray(cl, u, [], @mean);
                inv = cl(inv);
                return
            end
            if isempty(opts.Round) && numel(u) > 1 && any(u ~= round(u))
                scale = max([u(end) - u(1), abs(u(1)), abs(u(end))]);
                close = find(diff(u) <= 1e-9 * scale);
                if ~isempty(close)
                    warning('lbd:nearEqual', ['toDense: "%s" has coordinates that differ only by rounding (%.17g and %.17g): ' ...
                        'they become separate ticks. Merge them with Round= or RTol= / ATol='], name, u(close(1)), u(close(1) + 1));
                end
            end
            t = u;
        end

        function x = fillLike(data, sz)
            %FILLLIKE  Rows of "not measured" of DATA's type: NaN, or 0 / false.
            if isfloat(data)
                x = nan(sz, class(data));
                if ~isreal(data), x = complex(x, x); end
            elseif islogical(data)
                x = false(sz);
            else
                x = zeros(sz, class(data));
            end
        end
    end

    methods (Access = private)
        function validateLoaded(obj)
            for g = string(fieldnames(obj.Groups))'
                order = obj.Groups.(g).Order;
                above = 0;
                for k = 1:numel(order)
                    ax = obj.Axes.(order(k));
                    if any(~isfinite(ax.Data))
                        error('lbd:invalid', 'axis "%s" of group "%s" contains NaN or Inf', order(k), g);
                    end
                    keys = [zeros(numel(ax.Data), 1) ax.Data(:)];
                    if k > 1
                        if numel(ax.Parent) ~= numel(ax.Data)
                            error('lbd:invalid', '"%s._parent" has %d entries for %d points', order(k), numel(ax.Parent), numel(ax.Data));
                        end
                        if any(ax.Parent < 1 | ax.Parent > above)
                            error('lbd:invalid', '"%s._parent" points outside "%s" (0 ... %d in the file)', order(k), order(k-1), above - 1);
                        end
                        keys(:, 1) = double(ax.Parent(:));
                    end
                    if size(unique(keys, 'rows'), 1) < size(keys, 1)
                        warning('lbd:duplicatePoint', ['group "%s" has the same point twice on level "%s" (same coordinate ' ...
                            'under the same outer point); both are kept'], g, order(k));
                    end
                    above = numel(ax.Data);
                end
            end
            vn = fieldnames(obj.Values);
            for i = 1:numel(vn)
                v = obj.Values.(vn{i});
                if isfield(obj.Axes, v.Name) || isfield(obj.Groups, v.Name)
                    error('lbd:invalid', '"%s" is used by an axis or group and a value', v.Name);
                end
                for k = 1:numel(v.Dims)
                    n = obj.dimLength(v.Dims{k});
                    if n ~= v.Shape(k)
                        error('lbd:invalid', 'value "%s": dimension %d has size %d but %s has %d points', ...
                            v.Name, k, v.Shape(k), strjoin(v.Dims{k}, ","), n);
                    end
                end
            end
        end
    end
end

function copyValue(src, where, gid, name)
% A value of an opened file copied into another file inside HDF5 (what write changed flushed first).
H5F.flush(src, 'H5F_SCOPE_GLOBAL');
H5O.copy(src, char(where), gid, char(name), 'H5P_DEFAULT', 'H5P_DEFAULT');
end

function rewriteDescription(fid, d)
% The description, metadata and saved view of an opened file, written in place.
for a = ["title" "description"]
    try, H5A.delete(fid, char(a)); catch, end
end
lbd_write_attr(fid, 'title', d.Title);
lbd_write_attr(fid, 'description', d.Description);
if H5L.exists(fid, 'meta', 'H5P_DEFAULT'), H5L.delete(fid, 'meta', 'H5P_DEFAULT'); end
gid = H5G.create(fid, 'meta', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
lbd_write_meta(gid, d.Meta, "meta");
H5G.close(gid);
if H5L.exists(fid, 'plot', 'H5P_DEFAULT'), H5L.delete(fid, 'plot', 'H5P_DEFAULT'); end
if ~isempty(d.Plot) || ~isempty(d.Style) || ~isempty(d.StyleName)
    gid = H5G.create(fid, 'plot', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
    if ~isempty(d.Plot), lbd_write_attr(gid, 'spec', lbd_to_json(d.Plot, "Plot")); end
    if ~isempty(d.Style), lbd_write_attr(gid, 'style', lbd_to_json(d.Style, "Style")); end
    if ~isempty(d.StyleName), lbd_write_attr(gid, 'style_name', d.StyleName); end
    if ~isempty(d.Matplotlib) && strlength(d.Matplotlib) > 0, lbd_write_attr(gid, 'matplotlib', d.Matplotlib); end
    H5G.close(gid);
end
end
