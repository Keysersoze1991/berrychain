# iPhone release: TestFlight and the App Store

The iPhone app is built and uploaded by GitHub's macOS machines
(`.github/workflows/ios.yml`); no Mac is needed. Apple's rules mean the
only way onto a phone is TestFlight or the App Store, so the "download"
for iPhone users is a TestFlight invitation link.

Bundle identifier: `link.berrychain.wallet`. Display name: BerryChain.

## Once: what the developer account holder does

All of this is at https://developer.apple.com/account and
https://appstoreconnect.apple.com. Keep the downloaded files together with
the Android keystore; they are the identity of the app.

1. **Team ID.** Account > Membership details. Ten characters, e.g. `AB12CD34EF`.
2. **App ID.** Certificates, Identifiers & Profiles > Identifiers > `+` >
   App IDs > App. Description "BerryChain", Bundle ID explicit
   `link.berrychain.wallet`. No capabilities needed.
3. **Distribution certificate.** Certificates > `+` > *Apple Distribution*.
   It asks for a certificate signing request: upload
   `app/ios/signing/distribution.csr` from this PC (already generated; its
   private key never leaves the PC). Download the resulting
   `distribution.cer` into `app/ios/signing/`.
4. **Provisioning profile.** Profiles > `+` > *App Store Connect*
   (distribution). Choose the App ID and the certificate, name it
   `BerryChain App Store`, download it into `app/ios/signing/` as
   `BerryChain_App_Store.mobileprovision`.
5. **App Store Connect API key.** App Store Connect > Users and Access >
   Integrations > App Store Connect API > `+`. Name "GitHub upload", access
   *App Manager*. Note the **Key ID** and the **Issuer ID**, and download the
   `.p8` file once (it can only be downloaded once) into `app/ios/signing/`.
6. **The app record.** App Store Connect > Apps > `+` > New App. Platform
   iOS, name BerryChain, primary language English (Australia), bundle ID
   `link.berrychain.wallet`, SKU `berrychain-ios`. Privacy policy URL
   https://berrychain.link/privacy.html.

Then tell the builder: the `.cer`, the profile and the `.p8` are in
`app/ios/signing/`, plus the Team ID, Key ID and Issuer ID. The builder
runs `python app/tool/ios_secrets.py`, which turns them into the seven
values below, written to `app/ios/signing/secrets.txt`.

## Once: repository secrets

GitHub > the repository > Settings > Secrets and variables > Actions >
New repository secret, one per line of `secrets.txt`. Copy each value
from its own `paste_NAME.txt` file (open, Ctrl+A, Ctrl+C) rather than
selecting it out of `secrets.txt`: two of the long values lost a few
characters that way. The workflow prints the SHA-256 of what it decoded
as a notice, so a bad paste shows up as a checksum that differs from
`shasum -a 256` of the local file.

| Secret | What |
|---|---|
| `APPLE_CERT_P12_BASE64` | the certificate and its private key, PKCS12, base64 |
| `APPLE_CERT_PASSWORD` | the password on that PKCS12 |
| `APPLE_PROFILE_BASE64` | the provisioning profile, base64 |
| `APPLE_TEAM_ID` | the ten-character Team ID |
| `ASC_KEY_ID` | the API key's Key ID |
| `ASC_ISSUER_ID` | the API key's Issuer ID |
| `ASC_KEY_P8_BASE64` | the `.p8` file, base64 |

## Every release

```bash
git tag ios-v0.5.1 && git push origin ios-v0.5.1
```

or Actions > iOS > Run workflow. The workflow compiles, tests, signs,
uploads to TestFlight and keeps the `.ipa` as an artifact for two weeks.
The build number is the run number, so every upload is newer than the
last; the version is the one in `pubspec.yaml`. The Xcode project pins
the team, manual signing, the "Apple Distribution" identity and the
"BerryChain App Store" profile for Release builds; without that,
`flutter build ipa` insists on a development certificate and stops.

After the first upload, in App Store Connect > TestFlight: add yourself
as an internal tester (instant), then create an external group, add the
build, fill the short "what to test" text, and submit for beta review
(usually a day). The public link for that group is what goes on the
website. Up to 10,000 testers, builds expire after 90 days, each new
upload refreshes them.

## The App Store itself

Same build. App Store Connect > App Store tab: screenshots for 6.7" and
6.5" iPhones, description (reuse docs/PLAY_LISTING.md), age rating
questionnaire, App Privacy answers (Data Not Collected), the export
compliance question (already answered in Info.plist: no non-exempt
encryption, since it only uses standard algorithms for end-to-end
messaging; if Apple asks, choose "standard encryption algorithms"), then
submit for review. First reviews take a few days; wallets get looked at
carefully, so the notes should say plainly that BERRY has no monetary
value and the app sells nothing.
