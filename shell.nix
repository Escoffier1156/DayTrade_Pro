{ pkgs ? import <nixpkgs> {} }:
pkgs.mkShell {
  buildInputs = with pkgs; [
    # regulars
    gfortran
    gnat         # 15.x: must match gprbuild and gnatprove's frontend generation
    gnatprove    # SPARK; nixpkgs derives its fsf-NN from the gnat above
    gprbuild
    verilator
    nodejs_24
    typescript
    yarn
    rustc
    cargo
    rust-analyzer
    (python3.withPackages (ps: with ps; [
      z3-solver
      hypothesis
      duckdb
      numpy
      matplotlib
      jax
      jaxlib
    ]))
    # reserves
    ocaml
    dune_3
    opam
    cbqn
    ngn-k
    beamPackages.elixir   # brings OTP
    beamPackages.erlang   # for erl / observer
    sbcl
    tlaplus
    jdk21       # required by tlc, not a language choice
    # bluespec  # unverified package name
    # lean4     # unverified package name
    # tools
    z3
    llvm_19
    llvmPackages_19.clang
    binutils
    pkg-config
    cmake        # gnumake already comes from stdenv
    git
    # debug / profile
    gdb
    llvmPackages_19.lldb   # matched to clang_19 above, not the top-level lldb 21
    valgrind
    hyperfine
    # linuxPackages.perf  # nixpkgs builds 7.1.3; host kernel is 7.0.0-29-generic.
                          # Ubuntu's /usr/bin/perf matches uname -r and stays on PATH here.
    # direnv              # belongs outside the shell: it is what enters it.
  ];
  shellHook = ''
    unalias tlc 2>/dev/null || true
    function tlc {
      ${pkgs.jdk21}/bin/java -cp "${pkgs.tlaplus}/share/java/tla2tools.jar" tlc2.TLC "$@"
    }
    export -f tlc
    echo "fortran    : $(gfortran --version 2>/dev/null | head -n1 || echo '-')"
    echo "gnat       : $(gnat --version 2>/dev/null | head -n1 || echo '-')"
    echo "verilator  : $(verilator --version 2>/dev/null || echo '-')"
    echo "typescript : $(tsc --version 2>/dev/null || echo '-')"
    echo "rustc      : $(rustc --version 2>/dev/null || echo '-')"
    echo "python     : $(python3 --version 2>/dev/null || echo '-')"
    echo "jax        : $(python3 -c 'import jax; print(jax.__version__)' 2>/dev/null || echo '-')"
    echo "ocaml      : $(ocaml -version 2>/dev/null || echo '-')"
    echo "bqn        : $(BQN --version 2>/dev/null | head -n1 || echo '-')"
    echo "k          : $(echo '"ok"' | k 2>/dev/null | head -n1 || echo '-')"
    echo "elixir     : $(elixir --version 2>/dev/null | tail -n1 || echo '-')"
    echo "erlang     : $(erl -noshell -eval 'io:format("~s~n",[erlang:system_info(otp_release)]),halt().' 2>/dev/null || echo '-')"
    echo "sbcl       : $(sbcl --version 2>/dev/null || echo '-')"
    echo "tlc        : $(tlc 2>&1 | head -n1)"
    echo "z3         : $(z3 --version 2>/dev/null || echo '-')"
    echo "gnatprove  : $(gnatprove --version 2>/dev/null | head -n1 || echo '-')"
  '';
}
