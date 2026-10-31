classdef Writer < handle
    %LBD.WRITER  Write a file while measuring: readers see the data as it comes, and a crash
    %   loses at most the last moments.
    %
    %   w = lbd.Writer("sweep.lbd", Title="Resonator power sweep");
    %   w.addAxis("power", p, Unit="dBm");
    %   w.addAxis("freq", f, Unit="Hz");
    %   w.addValue("S21", [], ["power" "freq"], Dtype="complex128");
    %   for i = 1:numel(p)
    %       w.write(power=i, S21=vna_trace(p(i)));
    %   end
    %   w.close();
    %
    %   Build it like an lbd.Dataset (addAxis, addValue without data, Meta), then write each
    %   point, trace or map as it is measured (see lbd.Dataset/write). It writes
    %   "sweep.lbd.writing"; close makes it "sweep.lbd". On an error, w.abort() (or clearing
    %   w) leaves the .writing file with what was measured ("stopped before finishing";
    %   lbd.recover makes it an .lbd file):
    %
    %   try
    %       ... measure, w.write(...) ...
    %       w.close();
    %   catch err
    %       w.abort();
    %       rethrow(err);
    %   end
    %
    %   Saving a whole dataset at the end with Dataset.save stays the simple way when nobody
    %   needs to look while it is measured. Needs HDF5 1.10 or newer in MATLAB.

    properties (Dependent)
        Title
        Description
        Meta
        Plot
        Style
        StyleName
    end

    properties (SetAccess = private)
        Path string                    % the finished file
        WritingPath string             % the file while written: Path + ".writing"
        FlushEvery (1,1) double = 0.5  % seconds between writes to the file
        ForceEvery (1,1) double = 2    % seconds between forcing the data to the disk
        State (1,1) string = "new"     % new, writing, finished, stopped
    end

    properties (Access = private)
        D                              % lbd.Dataset: the description and the checks
        Fid = []
        Raf = []                       % java.io.RandomAccessFile holding the guard
        GuardLock = []
        Pending = {}
        LastFlush = []
        LastForce = []
        FlushTimer = []
        Failure = []                   % MException from a background flush
    end

    properties (Constant, Hidden)
        GuardOffset = 2^40             % the guard's byte: beyond any data (spec section 7)
        FinishWait = 10                % seconds the finish waits for a program holding the file
    end

    methods
        function obj = Writer(path, opts)
            arguments
                path (1,1) string
                opts.Title (1,1) string = ""
                opts.Description (1,1) string = ""
                opts.Created = string.empty
                opts.FlushEvery (1,1) double {mustBePositive} = 0.5
                opts.ForceEvery (1,1) double {mustBePositive} = 2
            end
            [~, ~, ext] = fileparts(path);
            if lower(ext) ~= ".lbd"
                error('lbd:invalid', '%s: lbd.Writer writes .lbd files; give a name ending in .lbd', path);
            end
            obj.Path = path;
            obj.WritingPath = path + ".writing";
            for p = [obj.Path obj.WritingPath]
                if isfile(p)
                    error('lbd:exists', '%s exists; lbd.Writer never replaces a file - choose another name', p);
                end
            end
            obj.D = lbd.Dataset(opts.Title, opts.Description, Created=opts.Created);
            obj.D.LiveWriting = true;
            obj.FlushEvery = opts.FlushEvery;
            obj.ForceEvery = opts.ForceEvery;
        end

        function v = get.Title(obj), v = obj.D.Title; end
        function set.Title(obj, v), obj.D.Title = v; end
        function v = get.Description(obj), v = obj.D.Description; end
        function set.Description(obj, v), obj.D.Description = v; end
        function v = get.Meta(obj), v = obj.D.Meta; end
        function set.Meta(obj, v), obj.D.Meta = v; end
        function v = get.Plot(obj), v = obj.D.Plot; end
        function set.Plot(obj, v), obj.D.Plot = v; end
        function v = get.Style(obj), v = obj.D.Style; end
        function set.Style(obj, v), obj.D.Style = v; end
        function v = get.StyleName(obj), v = obj.D.StyleName; end
        function set.StyleName(obj, v), obj.D.StyleName = v; end

        function a = axes(obj), a = obj.D.Axes; end
        function v = values(obj), v = obj.D.Values; end
        function id = id(obj), id = obj.D.Id; end

        function axis = addAxis(obj, name, data, varargin)
            %ADDAXIS  As lbd.Dataset/addAxis; before the first write.
            if nargin < 3, data = []; end
            obj.beforeStart("addAxis");
            axis = obj.D.addAxis(name, data, varargin{:});
        end

        function value = addValue(obj, name, data, varargin)
            %ADDVALUE  As lbd.Dataset/addValue; before the first write. Without data ([]) the
            %   value is filled by write; with data it is written whole at the start.
            if nargin < 3, data = []; end
            obj.beforeStart("addValue");
            value = obj.D.addValue(name, data, varargin{:});
        end

        function start(obj)
            %START  Create the .writing file now (the first write does it otherwise).
            if obj.State ~= "new", return; end
            [major, minor] = H5.get_libversion();
            if major == 1 && minor < 10
                error('lbd:hdf5', ['writing while measuring needs HDF5 1.10 or newer; this MATLAB has %d.%d. ' ...
                    'Save the whole dataset at the end with lbd.Dataset/save instead'], major, minor);
            end
            if isempty(fieldnames(obj.D.Values))
                error('lbd:invalid', 'add at least one value before writing');
            end
            if isfile(obj.WritingPath) || isfile(obj.Path)
                error('lbd:exists', '%s exists; lbd.Writer never replaces a file', obj.WritingPath);
            end
            created = obj.D.Created;
            if isempty(created) || (isstring(created) && strlength(created) == 0)
                created = string(datetime('now', 'TimeZone', 'local', 'Format', "yyyy-MM-dd'T'HH:mm:ssxxx"));
            else
                created = lbd_created_text(created);
            end
            v = lbd.version();
            obj.D.setIdentity(lbd_uuid7(), created, "matlab lbd " + v.package);
            fapl = H5P.create('H5P_FILE_ACCESS');
            H5P.set_libver_bounds(fapl, 'H5F_LIBVER_V110', 'H5F_LIBVER_V110');   % the 1.10 format: SWMR needs it, every HDF5 since reads it
            fid = H5F.create(obj.WritingPath, 'H5F_ACC_EXCL', 'H5P_DEFAULT', fapl);
            H5P.close(fapl);
            try
                obj.takeGuard();                % at once: from now on it reads "measuring"
                obj.create(fid, v.lbd_version);
                H5F.start_swmr_write(fid);
            catch err
                H5F.close(fid);
                if ~isempty(obj.GuardLock)
                    obj.GuardLock.release();
                    obj.Raf.close();
                    obj.GuardLock = [];
                    obj.Raf = [];
                end
                delete(obj.WritingPath);
                rethrow(err);
            end
            obj.Fid = fid;
            obj.State = "writing";
            obj.LastFlush = tic;
            obj.LastForce = tic;
            lbd_own_writers("add", obj.WritingPath, fid);
        end

        function write(obj, varargin)
            %WRITE  Put measured data in its place: as lbd.Dataset/write.
            %   It returns at once; the data reaches the file within FlushEvery seconds (or at
            %   flush / close).
            obj.raiseFailure();
            if obj.State == "new", obj.start(); end
            if obj.State ~= "writing"
                error('lbd:closed', '%s: the Writer is closed; nothing more can be written', obj.Path);
            end
            plan = obj.D.planWrite(varargin);
            if ~isempty(plan.grow)
                ax = obj.D.Axes.(plan.grow.axis);
                obj.D.appendCoordinates(plan.grow.axis, plan.grow.coords);
                obj.Pending{end+1} = {"grow", plan.grow.axis, plan.grow.coords, numel(ax.Data) + numel(plan.grow.coords)};
            end
            for k = 1:numel(plan.puts)
                p = plan.puts{k};
                obj.Pending{end+1} = {"put", p.name, p.idx, p.data};
            end
            if toc(obj.LastFlush) >= obj.FlushEvery
                obj.writePending();
                obj.raiseFailure();
            else
                obj.flushSoon();
            end
        end

        function flush(obj)
            %FLUSH  Write everything collected so far to the file now (readers see it).
            obj.raiseFailure();
            if obj.State == "writing"
                obj.writePending();
                obj.raiseFailure();
            end
        end

        function path = close(obj, opts)
            %CLOSE  Finish: write what is left, close the file and rename it to Path.
            %   w.close(Stopped=true): the measurement was stopped on purpose; the points not
            %   measured stay NaN (or masked) without the warning about them.
            %   Returns the finished file: Path, or "name (2).lbd" if Path was made meanwhile.
            arguments
                obj
                opts.Stopped (1,1) logical = false
            end
            if obj.State == "new", obj.start(); end
            if obj.State ~= "writing"
                path = obj.Path;
                return
            end
            obj.checkDescription();             % bad metadata: still writing, nothing lost
            obj.stopTimer();
            obj.writePending();
            if ~isempty(obj.Failure)
                obj.abort();
                obj.raiseFailure();
            end
            H5F.close(obj.Fid);
            obj.Fid = [];
            try
                missing = obj.finishDescription();
            catch err
                obj.releaseGuard();
                obj.State = "stopped";
                rethrow(err);
            end
            obj.releaseGuard();
            if ~isempty(missing) && ~opts.Stopped
                warning('lbd:notMeasured', ['%s: %s not measured everywhere; the points not measured are marked ' ...
                    'in the file (close(Stopped=true) says the measurement was stopped on purpose)'], ...
                    obj.Path, strjoin(missing, ", "));
            end
            target = lbd_free_name(obj.Path);
            if target ~= obj.Path
                warning('lbd:exists', '%s was made by someone else while measuring; the measurement is saved as %s', ...
                    obj.Path, target);
            end
            started = tic;
            while ~java.io.File(char(obj.WritingPath)).renameTo(java.io.File(char(target)))
                if toc(started) > obj.FinishWait
                    obj.State = "stopped";
                    error('lbd:held', ['the measurement is complete, but another program kept %s open for %g s, so ' ...
                        'it couldn''t be renamed to %s. Close it there, then rename it yourself or use lbd.recover'], ...
                        obj.WritingPath, obj.FinishWait, target);
                end
                pause(0.1);
            end
            obj.State = "finished";
            obj.Path = target;
            path = target;
        end

        function abort(obj)
            %ABORT  Stop without finishing: what was written stays in the .writing file
            %   ("stopped before finishing"; lbd.recover makes it an .lbd file).
            if obj.State ~= "writing", return; end
            obj.stopTimer();
            try
                obj.writePending();
                H5F.close(obj.Fid);
            catch err
                obj.Fid = [];
                obj.releaseGuard();
                obj.State = "stopped";
                rethrow(err);
            end
            obj.Fid = [];
            obj.releaseGuard();
            obj.State = "stopped";
        end

        function delete(obj)
            % A Writer cleared or gone out of scope without close: keep what was measured.
            if obj.State == "writing"
                try
                    obj.abort();
                    warning('lbd:notClosed', ['%s was not closed; what was measured is in it ' ...
                        '(lbd.recover makes it an .lbd file)'], obj.WritingPath);
                catch
                end
            end
        end

        function disp(obj)
            fprintf('  lbd.Writer %s (%s)\n', obj.WritingPath, obj.State);
        end
    end

    methods (Hidden)
        function writePending(obj)
            if isempty(obj.Fid) || ~isempty(obj.Failure), return; end
            items = obj.Pending;
            obj.Pending = {};
            try
                for k = 1:numel(items)
                    obj.apply(items{k});
                end
                if ~isempty(items)
                    H5F.flush(obj.Fid, 'H5F_SCOPE_GLOBAL');
                end
                if toc(obj.LastForce) >= obj.ForceEvery
                    obj.Raf.getChannel().force(false);
                    obj.LastForce = tic;
                end
            catch err
                obj.Failure = err;
            end
            obj.LastFlush = tic;
        end
    end

    methods (Access = private)
        function beforeStart(obj, what)
            if obj.State ~= "new"
                error('lbd:invalid', '%s: give every axis and value before the first write (a file being written can''t get new ones)', what);
            end
        end

        function create(obj, fid, version)
            d = obj.D;
            lbd_write_attr(fid, 'lbd_format', "LBD");
            lbd_write_attr(fid, 'lbd_version', version);
            lbd_write_attr(fid, 'title', d.Title);
            lbd_write_attr(fid, 'description', d.Description);
            lbd_write_attr(fid, 'created', d.Created);
            lbd_write_attr(fid, 'writer', d.Writer);
            lbd_write_attr(fid, 'id', d.Id);
            gid = H5G.create(fid, 'axes', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
            for name = string(fieldnames(d.Axes))'
                a = d.Axes.(name);
                if a.Grows
                    did = lbd_live_dataset(gid, name, "float64", 0, true, NaN);
                else
                    did = lbd_write_dataset(gid, name, a.Data, 1, false);
                end
                lbd_write_attr(did, 'unit', a.Unit);
                lbd_write_attr(did, 'label', a.Label);
                if ~isempty(a.Elements), lbd_write_attr(did, 'elements', string(a.Elements), true); end
                if strlength(a.Role) > 0, lbd_write_attr(did, 'role', a.Role); end
                H5D.close(did);
            end
            H5G.close(gid);
            gid = H5G.create(fid, 'values', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
            masks = strings(1, 0);
            for name = string(fieldnames(d.Values))'
                v = d.Values.(name);
                grows = ~isempty(v.Axes) && d.Axes.(v.Axes(1)).Grows;
                if any(d.Placeholders == name)
                    did = lbd_live_dataset(gid, name, v.Dtype, v.Shape, grows, NaN);
                    if ~startsWith(v.Dtype, ["float" "complex"]), masks(end+1) = name; end %#ok<AGROW>
                else
                    data = v.Data;
                    if islogical(data), data = uint8(data); end
                    did = lbd_write_dataset(gid, name, data, numel(v.Axes), false);
                end
                lbd_write_attr(did, 'unit', v.Unit);
                lbd_write_attr(did, 'label', v.Label);
                lbd_write_attr(did, 'axes', strjoin(v.Axes, ","));
                if v.Dtype == "bool", lbd_write_attr(did, 'lbd_bool', int64(1)); end
                H5D.close(did);
            end
            H5G.close(gid);
            if ~isempty(masks)
                gid = H5G.create(fid, 'measured', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
                for name = masks
                    v = d.Values.(name);
                    grows = ~isempty(v.Axes) && d.Axes.(v.Axes(1)).Grows;
                    H5D.close(lbd_live_dataset(gid, name, "uint8", v.Shape, grows, 0));
                end
                H5G.close(gid);
            end
            gid = H5G.create(fid, 'meta', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
            lbd_write_meta(gid, d.Meta, "meta");
            H5G.close(gid);
        end

        function apply(obj, item)
            fid = obj.Fid;
            if item{1} == "grow"
                g = item{2};
                n = item{4};
                for name = string(fieldnames(obj.D.Values))'
                    v = obj.D.Values.(name);
                    if isempty(v.Axes) || v.Axes(1) ~= g, continue; end
                    lbd_live_extend(fid, "/values/" + name, n);
                    if H5L.exists(fid, '/measured', 'H5P_DEFAULT') && H5L.exists(fid, char("/measured/" + name), 'H5P_DEFAULT')
                        lbd_live_extend(fid, "/measured/" + name, n);
                    end
                end
                lbd_live_extend(fid, "/axes/" + g, n);
                c = item{3};
                lbd_live_put(fid, "/axes/" + g, {n - numel(c) + (1:numel(c))}, c, n);
            else
                name = item{2};
                v = obj.D.Values.(name);
                data = item{4};
                if islogical(data), data = uint8(data); end
                shape = v.Shape;
                for i = 1:numel(v.Axes)            % a growing axis: its length now
                    if obj.D.Axes.(v.Axes(i)).Grows, shape(i) = numel(obj.D.Axes.(v.Axes(i)).Data); end
                end
                lbd_live_put(fid, "/values/" + name, item{3}, data, shape);
                if H5L.exists(fid, '/measured', 'H5P_DEFAULT') && H5L.exists(fid, char("/measured/" + name), 'H5P_DEFAULT')
                    lbd_live_put(fid, "/measured/" + name, item{3}, ones(size(data), 'uint8'), shape);
                end
            end
        end

        function flushSoon(obj)
            % A one-off timer, so a burst of writes followed by a pause still reaches the file.
            if ~isempty(obj.FlushTimer) && isvalid(obj.FlushTimer), return; end
            t = timer('StartDelay', obj.FlushEvery, 'ExecutionMode', 'singleShot', 'Name', 'lbd.Writer flush');
            t.TimerFcn = @(~, ~) obj.writePending();
            t.StopFcn = @(src, ~) delete(src);
            obj.FlushTimer = t;
            start(t);
        end

        function stopTimer(obj)
            if ~isempty(obj.FlushTimer) && isvalid(obj.FlushTimer)
                stop(obj.FlushTimer);
            end
            obj.FlushTimer = [];
        end

        function raiseFailure(obj)
            if isempty(obj.Failure), return; end
            err = MException('lbd:write', ['writing %s failed: %s. What was written before is in %s; ' ...
                'lbd.recover makes it an .lbd file once this Writer is closed'], ...
                obj.WritingPath, obj.Failure.message, obj.WritingPath);
            err = err.addCause(obj.Failure);
            throw(err);
        end

        function takeGuard(obj)
            raf = java.io.RandomAccessFile(char(obj.WritingPath), 'rw');
            lock = raf.getChannel().tryLock(obj.GuardOffset, 1, false);
            if isempty(lock)
                raf.close();
                error('lbd:held', '%s is being written by another program', obj.WritingPath);
            end
            obj.Raf = raf;
            obj.GuardLock = lock;
        end

        function releaseGuard(obj)
            if ~isempty(obj.GuardLock)
                obj.GuardLock.release();
                obj.Raf.close();
            end
            obj.GuardLock = [];
            obj.Raf = [];
            lbd_own_writers("remove", obj.WritingPath);
        end

        function checkDescription(obj)
            d = obj.D;
            if ~isempty(d.Plot), lbd_to_json(d.Plot, "Plot"); end
            if ~isempty(d.Style), lbd_to_json(d.Style, "Style"); end
            fcpl = H5P.create('H5P_FILE_ACCESS');
            H5P.set_fapl_core(fcpl, 64 * 1024, false);
            fid = H5F.create(char("lbd-meta-check-" + string(feature('getpid'))), 'H5F_ACC_TRUNC', 'H5P_DEFAULT', fcpl);
            H5P.close(fcpl);
            cleanup = onCleanup(@() H5F.close(fid));
            gid = H5G.create(fid, 'meta', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
            groupCleanup = onCleanup(@() H5G.close(gid));
            lbd_write_meta(gid, d.Meta, "meta");
        end

        function missing = finishDescription(obj)
            % What SWMR can't change while writing: the description, metadata, saved view; and
            % the masks of values measured completely.
            d = obj.D;
            missing = strings(1, 0);
            fid = H5F.open(obj.WritingPath, 'H5F_ACC_RDWR', 'H5P_DEFAULT');
            cleanup = onCleanup(@() H5F.close(fid));
            for key = ["title" "description"]
                H5A.delete(fid, char(key));
            end
            lbd_write_attr(fid, 'title', d.Title);
            lbd_write_attr(fid, 'description', d.Description);
            H5L.delete(fid, 'meta', 'H5P_DEFAULT');
            gid = H5G.create(fid, 'meta', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
            lbd_write_meta(gid, d.Meta, "meta");
            H5G.close(gid);
            if ~isempty(d.Plot) || ~isempty(d.Style) || ~isempty(d.StyleName)
                gid = H5G.create(fid, 'plot', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
                if ~isempty(d.Plot), lbd_write_attr(gid, 'spec', lbd_to_json(d.Plot, "Plot")); end
                if ~isempty(d.Style), lbd_write_attr(gid, 'style', lbd_to_json(d.Style, "Style")); end
                if ~isempty(d.StyleName), lbd_write_attr(gid, 'style_name', d.StyleName); end
                H5G.close(gid);
            end
            if H5L.exists(fid, 'measured', 'H5P_DEFAULT')
                gid = H5G.open(fid, 'measured');
                for name = lbd_link_names(gid)
                    did = H5D.open(gid, char(name));
                    m = H5D.read(did);
                    H5D.close(did);
                    if all(m(:))
                        H5L.delete(gid, char(name), 'H5P_DEFAULT');
                    else
                        missing(end+1) = name; %#ok<AGROW>
                    end
                end
                left = numel(lbd_link_names(gid));
                H5G.close(gid);
                if left == 0
                    H5L.delete(fid, 'measured', 'H5P_DEFAULT');
                end
            end
        end
    end
end
