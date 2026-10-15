# Official SDK 57 compatibility evidence

Resolved on 2026-10-02 directly from npm registry metadata and Expo's source at the npm package's gitHead, not from another project.

- [expo 57.0.26 npm metadata](https://registry.npmjs.org/expo/57.0.26): gitHead `ad1efa3fa5802156660198ba5d787f91014d8df3`.
- [Official bundledNativeModules.json at that commit](https://raw.githubusercontent.com/expo/expo/ad1efa3fa5802156660198ba5d787f91014d8df3/packages/expo/bundledNativeModules.json). The installed `node_modules/expo/bundledNativeModules.json` was also inspected.
- [Official TypeScript template 57.0.28](https://registry.npmjs.org/expo-template-blank-typescript/57.0.28) recommends TypeScript `~6.0.3` and React types `~19.2.2`; both are pinned to their recommended base versions.

| Package | Official compatibility | Exact pin |
| --- | --- | --- |
| expo | SDK 57 | 57.0.26 |
| react | 19.2.3 | 19.2.3 |
| react-native | 0.86.3 | 0.86.3 |
| expo-location | ~57.0.20 | 57.0.20 |
| expo-task-manager | ~57.0.21 | 57.0.21 |
| expo-sqlite | ~57.0.3 | 57.0.3 |
| expo-crypto | ~57.0.3 | 57.0.3 |
| expo-status-bar | ~57.0.1 | 57.0.1 |
| react-native-safe-area-context | ~5.7.0 | 5.7.0 |
| @expo/vector-icons | ^15.0.2 | 15.0.2 |
| typescript | ~6.0.3, Expo template | 6.0.3 |
| @types/react | ~19.2.2, Expo template | 19.2.2 |
| @types/node | Node 24 test support, registry verified | 24.10.1 |

All direct versions were verified with `https://registry.npmjs.org/<package>/<version>`. The lockfile pins transitive versions and integrity digests. npm lifecycle scripts are disabled during installation; no global packages or Android/iOS toolchain installation is requested.

Implementation references: [Expo Location SDK57](https://docs.expo.dev/versions/v57.0.0/sdk/location/), [TaskManager SDK57](https://docs.expo.dev/versions/v57.0.0/sdk/task-manager/), [SQLite SDK57](https://docs.expo.dev/versions/v57.0.0/sdk/sqlite/). Configuration includes the location plugin's iOS background mode, Android background/foreground-service permissions, and top-level task registration. These configurations require a native binary and do not prove behavior on hardware.
