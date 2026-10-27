classdef Dataset < handle
    %LBD.DATASET  In-memory content of one LBD (.lbd) file.
    %
    %   d = lbd.Dataset("Resonator power sweep");
    %   d.addAxis("power", -40:4:0, Unit="dBm", Label="Power");
    %   d.addAxis("freq", linspace(4e9, 8e9, 401), Unit="Hz", Label="Frequency");
    %   d.addValue("S21", s21, ["power" "freq"]);      % size(s21) == [11 401]
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
    end

    properties (SetAccess = private)
        Axes (1,1) struct = struct()   % Axes.<name>   = struct(Name, Data, Unit, Label)
        Values (1,1) struct = struct() % Values.<name> = struct(Name, Data, Axes, Unit, Label, Shape, Dtype)
        Created string = string.empty
        Writer string = string.empty
        LbdVersion (1,1) string = "1.0"
        Path string = string.empty
    end

    methods
        function obj = Dataset(title, description)
            arguments
                title (1,1) string = ""
                description (1,1) string = ""
            end
            obj.Title = title;
            obj.Description = description;
        end

        function axis = addAxis(obj, name, data, opts)
            %ADDAXIS  Add a 1-D real axis.
            arguments
                obj
                name (1,1) string
                data
                opts.Unit (1,1) string = ""
                opts.Label string = string.empty
            end
            obj.checkNewName(name);
            if ~isvector(data) && ~isempty(data)
                error('lbd:invalid', 'axis "%s" must be 1-D, got size %s', name, mat2str(size(data)));
            end
            if ~(isnumeric(data) && isreal(data))
                error('lbd:invalid', 'axis "%s" must be real numeric, got %s', name, class(data));
            end
            label = opts.Label;
            if isempty(label), label = name; end
            axis = struct('Name', name, 'Data', data(:), 'Unit', opts.Unit, 'Label', label);
            obj.Axes.(name) = axis;
        end

        function value = addValue(obj, name, data, axes, opts)
            %ADDVALUE  Add an N-D value. AXES lists one axis name per dimension.
            %   d.addValue("S21", s21, ["power" "freq"])
            %   d.addValue("trace", y, "freq")
            %   d.addValue("fit_Q", 1.2e4)                 % scalar, no axes
            %   d.addValue("v", x, "freq", Dtype="float32")
            arguments
                obj
                name (1,1) string
                data
                axes = string.empty
                opts.Unit (1,1) string = ""
                opts.Label string = string.empty
                opts.Dtype (1,1) string = "auto"
            end
            obj.checkNewName(name);
            axesList = lbd.Dataset.axesList(axes);
            data = lbd.Dataset.coerce(data, opts.Dtype, name);
            nd = numel(axesList);
            if nd == 0
                if ~isscalar(data)
                    error('lbd:invalid', 'value "%s" is not scalar, so it needs axes', name);
                end
                shape = zeros(1, 0);
            elseif nd == 1
                if ~isvector(data)
                    error('lbd:invalid', 'value "%s" has %d dimension(s) but 1 axis was given', name, ndims(data));
                end
                wasComplex = ~isreal(data);
                data = data(:);
                % data(:) drops an all-zero imaginary part; keep complex data complex
                if wasComplex, data = complex(data); end
                shape = numel(data);
            else
                if ndims(data) > nd
                    error('lbd:invalid', 'value "%s" has %d dimension(s) but %d axes were given', name, ndims(data), nd);
                end
                shape = size(data, 1:nd);
            end
            for i = 1:nd
                ax = axesList(i);
                if ~isfield(obj.Axes, ax)
                    error('lbd:invalid', 'value "%s": axis "%s" does not exist; add it with addAxis first', name, ax);
                end
                n = numel(obj.Axes.(ax).Data);
                if n ~= shape(i)
                    error('lbd:invalid', 'value "%s": dimension %d has size %d but axis "%s" has length %d', ...
                        name, i, shape(i), ax, n);
                end
            end
            label = opts.Label;
            if isempty(label), label = name; end
            value = struct('Name', name, 'Data', data, 'Axes', axesList, 'Unit', opts.Unit, ...
                'Label', label, 'Shape', shape, 'Dtype', lbd_dtype_name(data));
            obj.Values.(name) = value;
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
            if lower(ext) ~= ".lbd"
                warning('lbd:extension', '%s: LBD files should use the .lbd extension', path);
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
            tmp = path + ".tmp-" + string(feature('getpid'));
            try
                obj.writeFile(tmp, opts.Compression);
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

        function writeFile(obj, path, compression)
            created = string(datetime('now', 'TimeZone', 'local', 'Format', "yyyy-MM-dd'T'HH:mm:ssxxx"));
            v = lbd.version();
            writer = "matlab lbd " + v.package;
            fid = H5F.create(path, 'H5F_ACC_TRUNC', 'H5P_DEFAULT', 'H5P_DEFAULT');
            closer = onCleanup(@() H5F.close(fid));
            lbd_write_attr(fid, 'lbd_format', "LBD");
            lbd_write_attr(fid, 'lbd_version', v.lbd_version);
            lbd_write_attr(fid, 'title', obj.Title);
            lbd_write_attr(fid, 'description', obj.Description);
            lbd_write_attr(fid, 'created', created);
            lbd_write_attr(fid, 'writer', writer);

            gid = H5G.create(fid, 'axes', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
            an = fieldnames(obj.Axes);
            for i = 1:numel(an)
                a = obj.Axes.(an{i});
                did = lbd_write_dataset(gid, a.Name, a.Data, 1, compression);
                lbd_write_attr(did, 'unit', a.Unit);
                lbd_write_attr(did, 'label', a.Label);
                H5D.close(did);
            end
            H5G.close(gid);

            gid = H5G.create(fid, 'values', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
            vn = fieldnames(obj.Values);
            for i = 1:numel(vn)
                val = obj.Values.(vn{i});
                data = val.Data;
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
            obj.LbdVersion = v.lbd_version;
        end
    end

    methods (Static, Hidden)
        function d = fromFile(path, loadAll, names)
            %FROMFILE  Used by lbd.load / lbd.info. With loadAll=false, only the values in
            %   NAMES (string array, may be empty) get their data read.
            path = string(path);
            if ~isfile(path)
                error('lbd:notFound', 'file not found: %s', path);
            end
            [~, fname, fext] = fileparts(path);
            base = fname + fext;
            fid = H5F.open(path, 'H5F_ACC_RDONLY', 'H5P_DEFAULT');
            closer = onCleanup(@() H5F.close(fid));

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
                    d.Axes.(name) = struct('Name', name, 'Data', data(:), ...
                        'Unit', lbd_attr_or(did, 'unit', ""), 'Label', lbd_attr_or(did, 'label', name));
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
                        'Shape', shape, 'Dtype', dtype);
                    found(end+1) = name; %#ok<AGROW>
                    H5D.close(did);
                end
                H5G.close(gid);
            end
            if ~loadAll && ~isempty(names)
                missing = setdiff(names, found);
                if ~isempty(missing)
                    error('lbd:notFound', '%s: no value(s) named %s', base, strjoin(missing, ", "));
                end
            end
            d.validateLoaded();
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

        function data = realOnly(data, dtype, name)
            if ~isreal(data)
                error('lbd:invalid', 'value "%s" is complex; refusing to drop the imaginary part (Dtype="%s")', name, dtype);
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
            end
        end
    end
end
