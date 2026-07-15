// Minimal module declarations for test-only Babel usage (React Compiler
// regression checks). These packages ship no bundled types; we only need the
// call sites in *.compiler.test.ts to type-check.
declare module '@babel/core' {
  const babel: {
    transformSync(
      code: string,
      options?: Record<string, unknown>,
    ): { code?: string | null } | null
  }
  export default babel
}

declare module 'babel-plugin-react-compiler' {
  const plugin: unknown
  export default plugin
}
