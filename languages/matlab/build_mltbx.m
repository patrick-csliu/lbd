function build_mltbx(srcDir, outFile, version)
%BUILD_MLTBX  Package matlab/+lbd as LBD.mltbx (needs MATLAB R2023a or newer to build;
%   the resulting toolbox installs on R2021b and newer).
%   matlab -batch "addpath('languages/matlab'); build_mltbx('languages/matlab', 'out/LBD.mltbx', '0.1.0')"
srcDir = char(java.io.File(srcDir).getCanonicalPath());
% Fixed identifier: MATLAB uses it to recognise upgrades of the same toolbox.
opts = matlab.addons.toolbox.ToolboxOptions(srcDir, "3f0b6f64-6a0e-4f43-9c3e-7d2f5f8b1a21");
opts.ToolboxName = "LBD";
% Toolbox versions are numbers only: a development build (1.2.0-dev) is packaged as 1.2.0.
opts.ToolboxVersion = char(erase(string(version), "-dev"));
opts.Summary = "Read and write LBD (.lbd) lab data files";
opts.Description = "LBD is an HDF5-based file format for measurement and simulation data that " + ...
    "reads and writes identically from every language LBD supports. Use lbd.Dataset, lbd.load and lbd.info.";
opts.AuthorName = "Patrick Liu";
opts.MinimumMatlabRelease = "R2021b";
files = dir(fullfile(srcDir, '+lbd', '**', '*.m'));
opts.ToolboxFiles = string(fullfile({files.folder}, {files.name}));
opts.ToolboxMatlabPath = string(srcDir);
outDir = fileparts(outFile);
if ~isempty(outDir) && ~isfolder(outDir), mkdir(outDir); end
opts.OutputFile = char(outFile);
matlab.addons.toolbox.packageToolbox(opts);
fprintf('wrote %s\n', outFile);
end
