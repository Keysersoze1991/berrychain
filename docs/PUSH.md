# Instant notices: the opt-in push relay

iPhone runs an app's background refresh when it feels like it, and never
for an app the user has swiped away, so "tell me when a letter arrives"
could be hours late or never. The push relay fixes that for people who
choose it. It is the one place where a server of ours learns which phone
belongs to which address, which is why it is opt-in, documented in the
privacy policy, and keeps nothing else.

## How it works

1. In Settings the user turns on **Tell me straight away** (iPhone only).
   The app asks Apple for a push token, signs
   `berrychain-push|register|<address>|ios|<token>|<unix time>` with the
   wallet's signing key, and POSTs it to `/push/register` on the first seed
   that answers.
2. `berrychain.push` (a small service beside the node on seed1) checks the
   signature against the address, and stores `token -> address`.
3. The relay follows the local node block by block. When a `SEND_LETTER`
   to a registered address is carried, it sends an Apple push to every
   token for that address: title "A letter has arrived", body "Sealed, and
   waiting for you." No sender, no content, no amount.
4. Switching the setting off POSTs a signed `/push/unregister`; a token
   Apple reports dead is forgotten on the spot.

Only Apple is implemented. Android's WorkManager runs the app's own check
every fifteen minutes reliably enough.

## Server setup (seed1)

Done once by the builder, after the account holder provides the APNs key:

```bash
# on seed1, as root
cp /opt/berrychain/deploy/push.env.example /etc/berrychain/push.env
# put the APNs .p8 at /etc/berrychain/apns.p8 (scp from the launch PC; never commit it)
chmod 640 /etc/berrychain/push.env /etc/berrychain/apns.p8
chown root:berry /etc/berrychain/push.env /etc/berrychain/apns.p8
# fill in APNS_KEY_ID in push.env (the ten-character Key ID shown in the portal)
mkdir -p /var/lib/berrychain/push && chown berry:berry /var/lib/berrychain/push
# the installer installs and starts the unit when push.env exists
SEED_HOST=seed1.berrychain.link bash /opt/berrychain/deploy/install.sh
curl -s https://seed1.berrychain.link/push/status
```

`/push/status` answers `{"registered": n, "height": h, "sent": s,
"dropped": d, "apns": true}`. `apns: false` means the three `APNS_*`
values are missing and the relay is running dry.

The nginx site routes `/push/` to port 8803 (`deploy/nginx-seed.conf`);
an existing seed whose nginx file predates this needs the `location /push/`
block pasted into `/etc/nginx/sites-available/berrychain` and
`systemctl reload nginx`.

## What the Apple account holder does (once)

At https://developer.apple.com/account, Certificates, Identifiers & Profiles:

1. **Key.** Keys > `+`. Name "BerryChain push", tick *Apple Push
   Notifications service (APNs)*, Continue, Register. Download the `.p8`
   once (it cannot be downloaded again) and note the **Key ID**. This file
   is a credential: keep it with the signing material, hand it to the
   builder for seed1 only.
2. **App ID.** Identifiers > `link.berrychain.wallet` > tick *Push
   Notifications* > Save.
3. **Profile.** Profiles > `BerryChain App Store` > Edit > Save (this
   regenerates it with the push capability) > Download. Replace
   `app/ios/signing/BerryChain_App_Store.mobileprovision`, run
   `python app/tool/ios_secrets.py`, and paste the new `APPLE_PROFILE_BASE64`
   value into the GitHub secret. A build signed with the old profile is
   refused by Apple because the app now carries the `aps-environment`
   entitlement.

The entitlement lives in `app/ios/Runner/Runner.entitlements`
(`aps-environment = production`, right for TestFlight and the App Store;
a debug build run from Xcode would need `development`).

## Checking it

```bash
curl -s https://seed1.berrychain.link/push/status
journalctl -u berrychain-push -n 50 --no-pager
```

On a phone with the switch on, have someone write to it: the push should
arrive within a block of the letter being carried (about a minute).
