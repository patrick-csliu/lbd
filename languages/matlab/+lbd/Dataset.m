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
        % Axes.<name> = struct(Name, Data, Unit, Label, Elements, Role, Grows): Elements, a text
        % per position (string.empty: numbered); Role, "point" for an axis of a value's data
        % point; Grows, true for an axis whose points write adds (addAxis(..., Grows=true))
        Axes (1,1) struct = struct()
        % Values.<name> = struct(Name, Data, Axes, Unit, Label, Shape, Dtype, PointAxes, Elements,
        % Measured): PointAxes, the axes of one data point (the last of Axes); Elements, a cell
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

        function axis = addAxis(obj, name, data, opts)
            %ADDAXIS  Add a 1-D real axis.
            %   d.addAxis("power", -40:4:0, Unit="dBm")
            %   d.addAxis("state", [], Elements=["ground" "excited"])   % numbered 0, 1
            %   d.addAxis("time", [], Unit="s", Grows=true)   % points added by write
            arguments
                obj
                name (1,1) string
                data = []
                opts.Unit (1,1) string = ""
                opts.Label string = string.empty
                opts.Elements = string.empty
                opts.Grows (1,1) logical = false
            end
            obj.checkNewName(name);
            if opts.Grows
                if ~isempty(data) || ~isempty(opts.Elements)
                    error('lbd:invalid', 'axis "%s" grows: give no data or Elements; write adds its points', name);
                end
                label = opts.Label;
                if isempty(label), label = name; end
                axis = struct('Name', name, 'Data', zeros(0, 1), 'Unit', opts.Unit, 'Label', label, ...
                    'Elements', string.empty, 'Role', "", 'Grows', true);
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
            axis = struct('Name', name, 'Data', data(:), 'Unit', opts.Unit, 'Label', label, ...
                'Elements', elements, 'Role', "", 'Grows', false);
            obj.Axes.(name) = axis;
        end

        function value = addValue(obj, name, data, axes, opts)
            %ADDVALUE  Add an N-D value. AXES lists one axis name per dimension.
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
            axesList = lbd.Dataset.axesList(axes);
            point = opts.Shape(:)';
            if any(point < 1 | point ~= round(point))
                error('lbd:invalid', 'value "%s": Shape must hold whole numbers of at least 1, not %s', name, mat2str(opts.Shape));
            end
            nd = numel(axesList);
            total = nd + numel(point);
            measured = [];
            placeholder = false;
            if isempty(data)                   % filled later by write: "not measured yet"
                for i = 1:nd
                    if ~isfield(obj.Axes, axesList(i))
                        error('lbd:invalid', 'value "%s": axis "%s" does not exist; add it with addAxis first', name, axesList(i));
                    end
                end
                shape = [arrayfun(@(a) numel(obj.Axes.(a).Data), axesList), point];
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
                ax = axesList(i);
                if ~isfield(obj.Axes, ax)
                    error('lbd:invalid', 'value "%s": axis "%s" does not exist; add it with addAxis first', name, ax);
                end
                n = numel(obj.Axes.(ax).Data);
                if n ~= shape(i)
                    hint = '';
                    if ~isempty(point) && ~isequal(shape(nd+1:end), point)
                        hint = '; the value''s axes come first, then the data point (e.g. transpose it)';
                    end
                    error('lbd:invalid', 'value "%s": dimension %d has size %d but axis "%s" has length %d%s', ...
                        name, i, shape(i), ax, n, hint);
                end
            end
            if ~isempty(point) && ~isequal(shape(nd+1:end), point)
                error('lbd:invalid', 'value "%s": its data points have size %s, not Shape=%s', ...
                    name, mat2str(shape(nd+1:end)), mat2str(point));
            end
            named = lbd.Dataset.valueElements(opts.Elements, point, name);
            pointNames = name + "_dim" + string(1:numel(point));
            for k = 1:numel(point)
                if isfield(obj.Axes, pointNames(k)) || isfield(obj.Values, pointNames(k))
                    error('lbd:invalid', ['value "%s" needs the name "%s" for an axis of its data points, but ' ...
                        'it is already used; rename that axis or value'], name, pointNames(k));
                end
            end
            label = opts.Label;
            if isempty(label), label = name; end
            for k = 1:numel(point)
                plabel = label;
                if numel(point) > 1, plabel = label + " (dim" + k + ")"; end
                obj.Axes.(pointNames(k)) = struct('Name', pointNames(k), 'Data', int64(0:point(k) - 1)', ...
                    'Unit', "", 'Label', plabel, 'Elements', named{k}, 'Role', "point", 'Grows', false);
            end
            axesList = [axesList pointNames];
            if isempty(dtypeName), dtypeName = lbd_dtype_name(data); end
            value = struct('Name', name, 'Data', data, 'Axes', axesList, 'Unit', opts.Unit, ...
                'Label', label, 'Shape', shape, 'Dtype', dtypeName, ...
                'PointAxes', pointNames, 'Elements', {named}, 'Measured', measured);
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

        function write(obj, varargin)
            %WRITE  Put measured data into values made by addValue: a point, a trace, a whole
            %   map, or several values at once, at the place the axes say.
            %   d.write(power=3, S21=trace)            % a trace: power 3, every frequency
            %   d.write(power=3, freq=7, S21=z, T=t)   % a point, and T at power 3
            %   d.write(state="excited", power=1, n=7) % a position by its element
            %   d.write(time=12.5, T=4.2)              % a growing axis: adds a point
            %   d.write("if", 3, "S21", z)             % any name, as text
            %   A fixed axis takes an index (1 = its first point) or one of its elements; a
            %   growing axis its coordinate(s); a value its data, sized as the value's axes that
            %   weren't given (and its data point), in order. Writing again replaces.
            plan = obj.planWrite(varargin);
            obj.applyWrite(plan);
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
            %   never sees a half-written file.
            arguments
                obj
                path (1,1) string
                opts.Compression (1,1) logical = false
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
            obj.Path = path;
            obj.Id = id;
            obj.ParentId = parent;
        end

        function disp(obj)
            fprintf('  lbd.Dataset "%s"\n', obj.Title);
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
            if isfield(obj.Axes, name) || isfield(obj.Values, name)
                error('lbd:invalid', 'name "%s" is already used by an axis or value', name);
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
            an = fieldnames(obj.Axes);
            for i = 1:numel(an)
                a = obj.Axes.(an{i});
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
            H5G.close(gid);

            gid = H5G.create(fid, 'values', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
            vn = fieldnames(obj.Values);
            for i = 1:numel(vn)
                val = obj.Values.(vn{i});
                data = val.Data;
                if startsWith(val.Dtype, "complex") && isreal(data)
                    data = complex(data);           % MATLAB drops an all-zero imaginary part
                end
                isBool = islogical(data);
                if isBool, data = uint8(data); end
                did = lbd_write_dataset(gid, val.Name, data, numel(val.Axes), compression);
                lbd_write_attr(did, 'unit', val.Unit);
                lbd_write_attr(did, 'label', val.Label);
                lbd_write_attr(did, 'axes', strjoin(val.Axes, ","));
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
                    did = lbd_write_dataset(gid, val.Name, uint8(val.Measured), numel(val.Axes), compression);
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
            if writing
                warning('lbd:writing', ['%s is still being written, or its writer stopped before finishing ' ...
                    '(lbd.writingStatus tells which); reading what was written so far'], base);
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
                    d.Axes.(name) = struct('Name', name, 'Data', data(:), ...
                        'Unit', lbd_attr_or(did, 'unit', ""), 'Label', lbd_attr_or(did, 'label', name), ...
                        'Elements', reshape(string(elements), 1, []), 'Role', role, 'Grows', false);
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
                        'Axes', lbd.Dataset.axesList(lbd_attr_or(did, 'axes', "")), ...
                        'Unit', lbd_attr_or(did, 'unit', ""), 'Label', lbd_attr_or(did, 'label', name), ...
                        'Shape', shape, 'Dtype', dtype, 'PointAxes', strings(1, 0), 'Elements', {{}}, ...
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
            if writing                 % a growing axis and its values may be caught mid-write
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
            %   (lbd.Writer uses the same plan).
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
            isAxis = arrayfun(@(n) isfield(obj.Axes, n), names);
            isValue = arrayfun(@(n) isfield(obj.Values, n), names);
            if any(~isAxis & ~isValue)
                error('lbd:invalid', 'write: no axis or value named %s; axes: %s; values: %s', ...
                    strjoin(names(~isAxis & ~isValue), ", "), strjoin(string(fieldnames(obj.Axes)), ", "), ...
                    strjoin(string(fieldnames(obj.Values)), ", "));
            end
            if ~any(isValue)
                error('lbd:invalid', 'write: give at least one value with its data, e.g. write(power=3, S21=trace)');
            end
            pos = struct();
            grow = [];
            for k = find(isAxis)
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
                idx = cell(1, numel(v.Axes));
                need = zeros(1, 0);
                free = strings(1, 0);
                for i = 1:numel(v.Axes)
                    a = v.Axes(i);
                    ax = obj.Axes.(a);
                    if ax.Grows
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
                data = lbd.Dataset.fitsType(given{k}, v.Dtype, name);
                data = lbd.Dataset.shapedFor(data, need, name, free);
                puts{end+1} = struct('name', name, 'idx', {idx}, 'data', data); %#ok<AGROW>
            end
            plan = struct('grow', grow, 'puts', {puts});
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
                ax = obj.Axes.(g);
                ax.Data = [double(ax.Data); c];
                obj.Axes.(g) = ax;
                vn = string(fieldnames(obj.Values))';
                for name = vn
                    v = obj.Values.(name);
                    if isempty(v.Axes) || v.Axes(1) ~= g, continue; end
                    sz = size(v.Data);
                    sz(1) = numel(c);
                    if ~isfloat(v.Data) && isempty(v.Measured)
                        v.Measured = true(size(v.Data));
                    end
                    v.Data = cat(1, v.Data, lbd.Dataset.fillLike(v.Data, sz));
                    if ~isempty(v.Measured)
                        v.Measured = cat(1, v.Measured, false(sz));
                    end
                    v.Shape(1) = v.Shape(1) + numel(c);
                    obj.Values.(name) = v;
                end
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
                if startsWith(v.Dtype, "complex") && isreal(v.Data)
                    v.Data = complex(v.Data);       % MATLAB drops an all-zero imaginary part
                end
                obj.Values.(p.name) = v;
            end
        end

        function sameLengths(obj)
            %SAMELENGTHS  In a file being written, cut each axis and the values on it to the
            %   length all of them have reached (the writer extends them one after the other).
            an = string(fieldnames(obj.Axes))';
            vn = string(fieldnames(obj.Values))';
            for a = an
                n = numel(obj.Axes.(a).Data);
                for name = vn
                    k = find(obj.Values.(name).Axes == a, 1);
                    if ~isempty(k) && k <= numel(obj.Values.(name).Shape)
                        n = min(n, obj.Values.(name).Shape(k));
                    end
                end
                if n < numel(obj.Axes.(a).Data)
                    obj.Axes.(a).Data = obj.Axes.(a).Data(1:n);
                end
                for name = vn
                    v = obj.Values.(name);
                    k = find(v.Axes == a, 1);
                    if isempty(k) || v.Shape(k) <= n, continue; end
                    v.Shape(k) = n;
                    sz = v.Shape;
                    if numel(sz) == 1, sz = [sz 1]; end
                    if ~isempty(v.Data), v.Data = lbd.Dataset.cutTo(v.Data, sz); end
                    if ~isempty(v.Measured), v.Measured = lbd.Dataset.cutTo(v.Measured, sz); end
                    obj.Values.(name) = v;
                end
            end
        end

        function appendCoordinates(obj, axis, coords)
            %APPENDCOORDINATES  Points added to a growing axis (lbd.Writer).
            obj.Axes.(axis).Data = [double(obj.Axes.(axis).Data); coords(:)];
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
            vn = fieldnames(obj.Values);
            for i = 1:numel(vn)
                v = obj.Values.(vn{i});
                if numel(v.Axes) ~= numel(v.Shape)
                    error('lbd:invalid', 'value "%s" has %d dimension(s) but axes=%s', v.Name, numel(v.Shape), strjoin(v.Axes, ","));
                end
                for k = 1:numel(v.Axes)
                    ax = v.Axes(k);
                    if ~isfield(obj.Axes, ax)
                        error('lbd:invalid', 'value "%s" refers to missing axis "%s"', v.Name, ax);
                    end
                    if numel(obj.Axes.(ax).Data) ~= v.Shape(k)
                        error('lbd:invalid', 'value "%s": dimension %d has size %d but axis "%s" has length %d', ...
                            v.Name, k, v.Shape(k), ax, numel(obj.Axes.(ax).Data));
                    end
                end
                % a data point's axes are the last ones with role "point"
                k = numel(v.Axes);
                while k > 0 && obj.Axes.(v.Axes(k)).Role == "point"
                    k = k - 1;
                end
                v.PointAxes = v.Axes(k+1:end);
                v.Elements = arrayfun(@(a) obj.Axes.(a).Elements, v.PointAxes, 'UniformOutput', false);
                obj.Values.(vn{i}) = v;
            end
        end
    end
end
