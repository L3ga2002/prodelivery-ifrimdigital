const fs = require('node:fs');
const path = require('node:path');
const { withAndroidManifest, withDangerousMod } = require('@expo/config-plugins');

const domains = ['root', 'file', 'database', 'sharedpref', 'external',
  'device_root', 'device_file', 'device_database', 'device_sharedpref'];
const excludes = domains.map(domain => `    <exclude domain="${domain}" path="." />`).join('\n');
const extractionRules = `<?xml version="1.0" encoding="utf-8"?>
<data-extraction-rules>
  <cloud-backup disableIfNoEncryptionCapabilities="true">
${excludes}
  </cloud-backup>
  <device-transfer>
${excludes}
  </device-transfer>
  <cross-platform-transfer platform="ios">
${excludes}
  </cross-platform-transfer>
</data-extraction-rules>
`;
const backupRules = `<?xml version="1.0" encoding="utf-8"?>
<full-backup-content>
${excludes}
</full-backup-content>
`;

module.exports = function withProbeBackupProtection(config) {
  config = withAndroidManifest(config, mod => {
    const application = mod.modResults.manifest.application?.[0];
    if (!application) throw new Error('Probe Android application manifest missing.');
    application.$['android:allowBackup'] = 'false';
    application.$['android:fullBackupContent'] = '@xml/prodelivery_full_backup_rules';
    application.$['android:dataExtractionRules'] = '@xml/prodelivery_data_extraction_rules';
    return mod;
  });
  return withDangerousMod(config, ['android', async mod => {
    const directory = path.join(mod.modRequest.platformProjectRoot, 'app/src/main/res/xml');
    fs.mkdirSync(directory, { recursive: true });
    fs.writeFileSync(path.join(directory, 'prodelivery_full_backup_rules.xml'), backupRules);
    fs.writeFileSync(path.join(directory, 'prodelivery_data_extraction_rules.xml'), extractionRules);
    return mod;
  }]);
};
