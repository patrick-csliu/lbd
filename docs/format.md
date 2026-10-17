# File format (LBD v1)

LBD ("Lab Data", extension `.lbd`) is a file format for measurement and simulation data that can
be written and read identically from any programming language with an LBD module, and viewed
with LBD Viewer.

An `.lbd` file **is a plain HDF5 file**. Every HDF5 tool (HDFView, `h5dump`, h5py, MATLAB
`h5info`, HDF5.jl) can open it. LBD only adds a fixed layout and a few conventions on top.

!!! info "This page is the specification"
    It is written for people implementing LBD in a new language, or reading `.lbd` files with
    plain HDF5 tools. For a plain-language introduction, see [Concepts](getting-started/concepts.md).
    Keywords **must**, **should** and **may** follow RFC 2119. The same text is in
    `spec/LBD-v1.md` in the repository.

--8<-- "spec/LBD-v1.md:body"
