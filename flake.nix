# Professional Go development environment for the confNotifier scraper/API.
#
#   nix develop            # enter the shell with all tools on PATH
#   nix develop -c go ...  # run any go command inside the shell
#
# Pins to the project's go.mod (go 1.26). If that toolchain version moves,
# bump `goVersion` below — nixpkgs will fetch the matching toolchain.
{
  description = "Professional Go development environment for confNotifier";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
  inputs.flake-utils.url = "github:numtide/flake-utils";

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        # Match go.mod's toolchain; bump if go.mod changes.
        goVersion = "1.26.0";
        go = pkgs.go.override { inherit goVersion; };
      in
      {
        devShells.default = pkgs.mkShell {
          # Tools available on PATH inside `nix develop`.
          packages = with pkgs; [
            go            # Go compiler/toolchain (pinned version above)
            gopls         # Go language server (editor integration)
            golangci-lint # combined linter (staticcheck, revive, …)
            delve         # debugger (dlv)
            gotoes        # goimports, gofmt, godoc, go vet wrappers
            go-tools      # cgo, go-mod, etc.
            git           # version control
            gnumake       # `make`
            docker        # container builds (Dockerfile.api)
          ];

          # Shell hooks: print a friendly banner and surface the module root.
          shellHook = ''
            echo "Go dev shell: go ${goVersion}, gopls, golangci-lint, delve, docker"
            echo "Module: confnotifier (see go_based_scraper/go.mod)"
          '';
        };
      });
}
