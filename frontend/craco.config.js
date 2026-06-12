// craco.config.js
const path = require("path");
require("dotenv").config();

// Environment variable overrides
const config = {
  enableHealthCheck: process.env.ENABLE_HEALTH_CHECK === "true",
};

// Conditionally load health check modules only if enabled
let WebpackHealthPlugin;
let setupHealthEndpoints;
let healthPluginInstance;

if (config.enableHealthCheck) {
  WebpackHealthPlugin = require("./plugins/health-check/webpack-health-plugin");
  setupHealthEndpoints = require("./plugins/health-check/health-endpoints");
  healthPluginInstance = new WebpackHealthPlugin();
}

const webpackConfig = {
  eslint: {
    configure: {
      extends: ["plugin:react-hooks/recommended"],
      rules: {
        "react-hooks/rules-of-hooks": "error",
        "react-hooks/exhaustive-deps": "warn",
      },
    },
  },
  webpack: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
    configure: (webpackConfig) => {

      // Add ignored patterns to reduce watched directories
        webpackConfig.watchOptions = {
          ...webpackConfig.watchOptions,
          ignored: [
            '**/node_modules/**',
            '**/.git/**',
            '**/build/**',
            '**/dist/**',
            '**/coverage/**',
            '**/public/**',
        ],
      };

      // Add health check plugin to webpack if enabled
      if (config.enableHealthCheck && healthPluginInstance) {
        webpackConfig.plugins.push(healthPluginInstance);
      }
      return webpackConfig;
    },
  },
};

webpackConfig.devServer = (devServerConfig) => {
  devServerConfig.historyApiFallback = {
    ...(typeof devServerConfig.historyApiFallback === "object" ? devServerConfig.historyApiFallback : {}),
    disableDotRule: true,
    htmlAcceptHeaders: ["text/html", "application/xhtml+xml", "*/*"],
  };

  const originalSetupMiddlewares = devServerConfig.setupMiddlewares;
  devServerConfig.setupMiddlewares = (middlewares, devServer) => {
    middlewares.unshift({
      name: "spa-navigation-fallback",
      middleware: (req, _res, next) => {
        if (req.method === "GET" && !req.headers.accept && !req.path.includes(".")) {
          req.headers.accept = "text/html";
        }
        next();
      },
    });

    if (originalSetupMiddlewares) {
      middlewares = originalSetupMiddlewares(middlewares, devServer);
    }

    if (config.enableHealthCheck && setupHealthEndpoints && healthPluginInstance) {
      setupHealthEndpoints(devServer, healthPluginInstance);
    }

    return middlewares;
  };

  return devServerConfig;
};

module.exports = webpackConfig;
