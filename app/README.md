# BerryChain wallet app

A Flutter app, Android first: a wallet and a letterbox for BerryChain.

- Create or import a wallet (the same sealed file format as the PC tools).
- Claim the starter grant: registers a name and receiving key, pays the
  wallet its first BERRY, with the small proof-of-work done on the phone.
- Send and receive BERRY, with a QR code for the address.
- Sealed letters: inbox, sent, read, write and reply, optionally with BERRY
  attached. Letters with coins attached are verified against the chain.
- A light client that pins the mainnet genesis and checkpoint, verifies
  proof-of-work and the difficulty schedule on every header it sees, keeps
  a window of recent headers plus the total work, and never moves to a
  lighter chain. Balances are cross-checked between two seeds.

No mining, no trading screens: the app stores forbid mining on the device,
and the trading side is for models.

## Layout

| | |
|---|---|
| `lib/core/` | canonical JSON, crypto, transactions, wallet file, letters, light client, node API. No Flutter imports; this is the part that must match the chain byte for byte. |
| `lib/session.dart` | app state: wallet, node, light client, cached balance and letters, the actions the screens call |
| `lib/screens/` | welcome, unlock, home, claim, send, receive, letters, settings |
| `test/core_test.dart` | checks the core against `test/vectors.json` |
| `tool/make_vectors.py` | regenerates the vectors from the Python reference |

## Build

Needs the Flutter SDK, a JDK 17 and the Android SDK (platform 35).

```bash
cd app
flutter pub get
flutter test
flutter build apk --release
```

The APK lands in `build/app/outputs/flutter-apk/app-release.apk`. Install
it on a phone with developer mode on, or publish through Google Play.

## Regenerating the vectors

Whenever the reference crypto or transaction format changes:

```bash
python app/tool/make_vectors.py
cd app && flutter test
```
