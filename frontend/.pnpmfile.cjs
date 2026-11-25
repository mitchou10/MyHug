// openapi-typescript (the generator of src/lib/schema.ts) reads the code with the JavaScript API of TypeScript, which
// TypeScript 7 (the native compiler this project builds with) does not have. It gets its own TypeScript 5, so the
// project keeps 7 for `tsc`.
module.exports = {
  hooks: {
    readPackage(pkg) {
      if (pkg.name === 'openapi-typescript') {
        delete pkg.peerDependencies?.typescript
        pkg.dependencies = { ...pkg.dependencies, typescript: '5.9.3' }
      }
      return pkg
    },
  },
}
