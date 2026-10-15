const { withAppBuildGradle, withMainApplication } = require('@expo/config-plugins');

const marker = '// ProDelivery local diagnostic variant';
const variant = `
${marker}
android {
  buildTypes {
    diagnostic {
      initWith release
      debuggable true
      matchingFallbacks = ['release']
      signingConfig signingConfigs.debug
      externalNativeBuild {
        cmake {
          arguments '-DCMAKE_BUILD_TYPE=RelWithDebInfo'
        }
      }
    }
  }
}
`;

module.exports = function withDiagnosticBuild(config) {
  config = withAppBuildGradle(config, mod => {
    if (mod.modResults.language !== 'groovy') throw new Error('Unsupported probe Gradle template.');
    if (!mod.modResults.contents.includes(marker)) mod.modResults.contents += variant;
    return mod;
  });
  return withMainApplication(config, mod => {
    if (mod.modResults.language !== 'kt') throw new Error('Unsupported probe Android application template.');
    const needle = 'context = applicationContext,';
    const explicit = 'useDevSupport = false,';
    if (!mod.modResults.contents.includes(explicit)) {
      if (mod.modResults.contents.split(needle).length !== 2) throw new Error('Unsupported Expo host template.');
      mod.modResults.contents = mod.modResults.contents.replace(needle, `${needle}\n      ${explicit}`);
    }
    return mod;
  });
};
