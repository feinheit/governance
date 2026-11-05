module.exports = (env, argv) => {
  const {
    base,
    devServer,
    assetRule,
    postcssRule,
    sassRule,
    swcWithPreactRule,
  } = require("./rspack.library.js")(argv.mode === "production")

  // No core-js: SWC's usage detection polyfills Array#map as an iterator
  // helper, Set#has as URLSearchParams#has etc., all browsers we support
  // have what the scripts use
  const swcRule = swcWithPreactRule()
  swcRule.options.env = {}

  return {
    ...base,
    // The circle browser as one file with Preact and d3, without a chunk of
    // its own for them
    optimization: { splitChunks: false },
    // rspack serve compiles dynamic imports lazily, but its requests to
    // /_rspack/lazy/trigger end up in Django (the proxy takes everything)
    lazyCompilation: false,
    devServer: devServer({ backendPort: env.backend }),
    module: {
      rules: [
        assetRule(),
        postcssRule({ plugins: ["autoprefixer"] }),
        sassRule(),
        swcRule,
      ],
    },
  }
}
