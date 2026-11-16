classdef OnDisk < matlab.mixin.indexing.RedefinesParen
    %LBD.ONDISK  A value's data in the file (lbd.open): its size and type without reading;
    %   indexing it with () reads only that part.
    %
    %   d = lbd.open("big.lbd");
    %   x = d.Values.S21.Data;   % an lbd.OnDisk
    %   size(x)                  % 50 1000000: nothing read
    %   row = x(4, :);           % reads row 4 only
    %   all = x(:, :);           % reads it all
    %   d.close();

    properties (SetAccess = private)
        Where string            % the dataset in the file, e.g. "/values/S21"
        Shape double            % its logical size (the spec's order), e.g. [50 1000000]
        Dtype string            % LBD type: "float64", "complex128", "bool", ...
    end

    properties (Access = private)
        Source                  % lbd.LazySource: the opened file
    end

    methods
        function obj = OnDisk(source, where, shape, dtype)
            obj.Source = source;
            obj.Where = string(where);
            obj.Shape = shape(:)';
            obj.Dtype = string(dtype);
        end

        function varargout = size(obj, varargin)
            sz = obj.Shape;
            if isempty(sz), sz = [1 1]; elseif isscalar(sz), sz = [sz 1]; end
            if nargin > 1
                d = [varargin{:}];
                out = ones(1, numel(d));
                out(d <= numel(sz)) = sz(d(d <= numel(sz)));
                sz = out;
            end
            if nargout <= 1
                varargout{1} = sz;
            else
                for k = 1:nargout
                    if k < nargout, varargout{k} = sz(k); else, varargout{k} = prod(sz(k:end)); end
                end
            end
        end

        function n = numel(obj, varargin)
            n = prod(obj.Shape);
        end

        function tf = isempty(obj)
            tf = prod(obj.Shape) == 0;
        end

        function x = read(obj)
            %READ  All of it.
            x = obj.readPart(repmat({':'}, 1, max(numel(obj.Shape), 1)));
        end

        function disp(obj)
            fprintf('  lbd.OnDisk %s %s %s (in the file; index it to read)\n', obj.Where, mat2str(obj.Shape), obj.Dtype);
        end
    end

    methods (Access = protected)
        function varargout = parenReference(obj, indexOp)
            x = obj.readPart(indexOp(1).Indices);
            if numel(indexOp) > 1
                x = x.(indexOp(2:end));
            end
            varargout{1} = x;
        end

        function obj = parenAssign(obj, indexOp, varargin)
            obj.Source.check("write");
            idx = indexOp(1).Indices;
            [start, count, take] = obj.box(idx);
            if any(cellfun(@(t) ~(ischar(t) && t == ':'), take))
                error('lbd:invalid', 'writing into an opened file takes indices and ranges of consecutive points');
            end
            data = varargin{1};
            if obj.Dtype == "bool", data = uint8(data); end
            if startsWith(obj.Dtype, "complex"), data = complex(data); end
            where = obj.Where;
            obj.Source.run(@(fid) writeBox(fid, where, start, count, data));
        end

        function n = parenListLength(~, ~, ~)
            n = 1;
        end

        function obj = parenDelete(obj, ~) %#ok<STOUT>
            error('lbd:invalid', 'a value in a file can''t have parts deleted');
        end
    end

    methods (Static)
        function obj = empty(varargin) %#ok<STOUT>
            error('lbd:invalid', 'lbd.OnDisk is made by lbd.open');
        end
    end

    methods (Hidden)
        function obj = cat(varargin) %#ok<STOUT>
            error('lbd:invalid', 'read the parts first (x(:, :)), then join them');
        end

        function x = readPart(obj, idx)
            % IDX: MATLAB subscripts (from 1); reads the box around them, then takes from it.
            nd = numel(obj.Shape);
            if nd == 0
                where = obj.Where;
                x = obj.Source.run(@(fid) readBox(fid, where, [], [], 0));
                x = obj.finish(x);
                if ~(isempty(idx) || all(cellfun(@(t) (ischar(t) && t == ':') || isequal(t, 1), idx)))
                    x = x(idx{:});
                end
                return
            end
            if numel(idx) ~= nd && ~(nd == 1 && numel(idx) == 2)
                x = obj.read();                         % linear indexing: read it all, then index
                x = x(idx{:});
                return
            end
            [start, count, take] = obj.box(idx);
            where = obj.Where;
            if any(count == 0)
                x = obj.finish(zeros([count ones(1, max(0, 2 - nd))]));
            else
                x = obj.finish(obj.Source.run(@(fid) readBox(fid, where, start, count, nd)));
            end
            if nd == 1, take = take(1); end
            if any(cellfun(@(t) ~(ischar(t) && t == ':'), take))
                if nd == 1
                    x = x(take{1});
                else
                    x = x(take{:});
                end
            end
            if nd == 1, x = x(:); end
        end
    end

    methods (Access = private)
        function [start, count, take] = box(obj, idx)
            % The box to read (C order, from 0) and what to take from it afterwards.
            nd = numel(obj.Shape);
            if nd == 1 && numel(idx) == 2
                if ~((ischar(idx{2}) && idx{2} == ':') || isequal(idx{2}, 1))
                    error('lbd:invalid', 'index exceeds the size of a 1-D value (its second index can only be 1)');
                end
                idx = idx(1);
            end
            start = zeros(1, nd);
            count = zeros(1, nd);
            take = repmat({':'}, 1, nd);
            for k = 1:nd
                n = obj.Shape(k);
                s = idx{k};
                if ischar(s) && s == ':'
                    count(k) = n;
                    continue
                end
                if islogical(s)
                    if numel(s) ~= n
                        error('lbd:invalid', 'a logical index must have %d elements for dimension %d', n, k);
                    end
                    s = find(s);
                end
                s = double(s(:));
                if any(s < 1 | s > n | s ~= round(s))
                    error('lbd:invalid', 'index out of range: dimension %d has %d points (1 ... %d)', k, n, n);
                end
                if isempty(s)
                    count(k) = 0;
                    take{k} = [];
                    continue
                end
                lo = min(s); hi = max(s);
                start(k) = lo - 1;
                count(k) = hi - lo + 1;
                if ~isequal(s', lo:hi), take{k} = s - lo + 1; end
            end
        end

        function x = finish(obj, x)
            if obj.Dtype == "bool", x = logical(x); end
            if startsWith(obj.Dtype, "complex") && isreal(x), x = complex(x); end
        end
    end
end

function x = readBox(fid, where, start, count, nd)
did = H5D.open(fid, char(where));
cleanup = onCleanup(@() H5D.close(did));
if nd == 0
    x = lbd_from_file_order(H5D.read(did), 0);
    return
end
fs = H5D.get_space(did);
cleanFile = onCleanup(@() H5S.close(fs));
H5S.select_hyperslab(fs, 'H5S_SELECT_SET', start, [], count, []);
ms = H5S.create_simple(nd, count, []);
cleanMem = onCleanup(@() H5S.close(ms));
x = lbd_from_file_order(H5D.read(did, 'H5ML_DEFAULT', ms, fs, 'H5P_DEFAULT'), nd);
end

function writeBox(fid, where, start, count, data)
idx = arrayfun(@(s, c) s + (1:c), start, count, 'UniformOutput', false);
lbd_live_put(fid, where, idx, data, start + count);
end
