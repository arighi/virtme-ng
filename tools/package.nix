# An EROFS (enhanced lightweight linux read-only filesystem)
# for a Nix Store containing:
# - the full dependency closure of packages listed in `passthru.packages`,
# - a convenient `passthru.package` merging `bin/` directories of packages
#   listed in `passthru.packages` in `${name}/`
#   so that they can easily be accessed at `/nix/store/${name}/bin/` in the VM.
{
  bash,
  buildEnv,
  closureInfo,
  emptyDirectory,
  erofs-utils,
  gnutar,
  hello,
  stdenv,
}:
stdenv.mkDerivation (finalAttrs: {
  name = "tools";

  passthru = {
    filesystem = {
      label = finalAttrs.name;
      UUID = "22e210b6-ff78-440b-9038-2e30cbaf3f36";
    };
    packages = [
      bash
      hello
    ];
    package = buildEnv {
      name = finalAttrs.name;
      paths = finalAttrs.passthru.packages;
      extraPrefix = "/${finalAttrs.name}";
      pathsToLink = [
        "/bin"
      ];
    };
  };

  src = emptyDirectory;

  buildPhase = ''
    mkdir -p "$out"
    (
    set -x
    ${gnutar}/bin/tar --create \
      --absolute-names \
      --verbatim-files-from \
      --transform 'flags=rSh;s|^${finalAttrs.passthru.package}/||' \
      --transform 'flags=rSh;s|^/nix/store/||' \
      --transform 'flags=rSh;s|~nix~case~hack~[[:digit:]]\+||g' \
      --files-from ${
        closureInfo {
          rootPaths = [ finalAttrs.passthru.package ];
        }
      }/store-paths |
    ${erofs-utils}/bin/mkfs.erofs \
      --quiet \
      --force-uid=0 \
      --force-gid=0 \
      -L ${finalAttrs.passthru.filesystem.label} \
      -U ${finalAttrs.passthru.filesystem.UUID} \
      -T 0 \
      -z lz4 \
      --hard-dereference \
      --tar=f \
      "$out"/nix-store.erofs
    )
  '';
})
