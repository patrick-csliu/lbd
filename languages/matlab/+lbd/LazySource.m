classdef (Hidden) LazySource < handle
    %LBD.LAZYSOURCE  The file a dataset opened with lbd.open reads from: held open, or opened for
    %   each read (a file being written: spec section 7 says readers don't keep it open).

    properties (SetAccess = private)
        Path string
        Mode string             % "r" or "r+"
        Writing logical
        Closed logical = false
    end

    properties (Access = private)
        Fid = []                % the held file, or [] (opened for each read)
    end

    methods
        function obj = LazySource(path, mode)
            obj.Path = string(path);
            obj.Mode = string(mode);
            obj.Writing = endsWith(lower(obj.Path), ".writing");
            if ~obj.Writing
                if obj.Mode == "r+"
                    obj.Fid = H5F.open(obj.Path, 'H5F_ACC_RDWR', 'H5P_DEFAULT');
                else
                    obj.Fid = H5F.open(obj.Path, 'H5F_ACC_RDONLY', 'H5P_DEFAULT');
                end
            end
        end

        function out = run(obj, fn)
            %RUN  fn(fid) with the file open; refused once closed.
            if obj.Closed
                [~, name, ext] = fileparts(obj.Path);
                error('lbd:closed', '%s is closed: open it again, or use lbd.load', name + ext);
            end
            if ~isempty(obj.Fid)
                fid = obj.Fid;
                closer = [];
            else
                fid = lbd_own_writers("get", obj.Path);
                closer = [];
                if isempty(fid)
                    fid = lbd_open_writing(obj.Path);
                    closer = onCleanup(@() H5F.close(fid));
                end
            end
            if nargout > 0
                out = fn(fid);
            else
                fn(fid);
            end
            clear closer
        end

        function check(obj, what)
            %CHECK  Refuse WHAT ("write", "save") unless opened with Mode="r+".
            [~, name, ext] = fileparts(obj.Path);
            if obj.Mode ~= "r+"
                error('lbd:readOnly', ['%s is opened read-only (Mode="r"): %s is refused. Open it with ' ...
                    'Mode="r+" to change it, or use lbd.load'], name + ext, what);
            end
            if obj.Closed
                error('lbd:closed', '%s is closed: open it again, or use lbd.load', name + ext);
            end
        end

        function close(obj)
            if ~isempty(obj.Fid)
                H5F.close(obj.Fid);
                obj.Fid = [];
            end
            obj.Closed = true;
        end

        function delete(obj)
            if ~isempty(obj.Fid)
                try, H5F.close(obj.Fid); catch, end
            end
        end
    end
end
