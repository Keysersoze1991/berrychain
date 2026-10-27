# Carrying letters between phones

From app 0.14, a letter does not need a connection at the moment it is written,
and on Android it can travel between phones with no internet at all.

## The outbox

A letter is sealed to its recipient and signed by the sender on the phone
before anything else happens. If no seed can be reached, the signed
transaction goes into the phone's outbox (`outbox.json`) instead of being lost,
and the app hands it to a seed the moment one answers: on the next refresh, the
next twenty-second poll, or the fifteen-minute background check.

Sealing offline needs two things the phone normally asks a seed for:

- the recipient's receiving key. The app remembers every receiving key it has
  seen (`encpubs.json`, filled from letters already sent), so a letter can be
  sealed offline to anyone written to before. A first letter to a new address
  still needs a connection.
- the next nonce. The app remembers the chain's view from the last refresh and
  counts the letters already queued, so several offline letters line up in
  order. If the chain refuses one later (for example because the same wallet
  sent something from another device meanwhile), the app says so and drops it.

The seal version follows the last block height the phone saw, so letters
sealed offline after the sealed-post upgrade still use seal v2.

## Nearby carriage (Android)

With the Settings switch "Carry letters for nearby pen pals" on, the app
advertises and looks for other BerryChain phones over Bluetooth and Wi-Fi
Direct using Google's Nearby Connections (service id `link.berrychain.carry`,
cluster strategy, connections accepted automatically). When two phones meet
they exchange their outboxes. A phone then carries what it was handed and
offers it to every other phone it meets; whichever phone next reaches a seed
delivers the lot.

What a carrier holds is only ever signed transactions. It cannot read a letter
(the seal is end to end), cannot change one (the signature covers everything),
and cannot replay one (the nonce). Nothing carried is executed on the phone;
it is only forwarded. Limits: 300 items, a week, 64 KB per transaction, twelve
hops. Carried items are dropped once the chain accepts or refuses them, so a
letter delivered by another phone leaves everyone's outbox at the next drain.

Permissions on Android: Bluetooth scan, advertise and connect, nearby Wi-Fi
devices, and location on versions before 12 (Android ties Bluetooth discovery
to location there). The app asks when the switch is turned on. Android also
needs location services switched on for Nearby to keep connections.

iPhone: the outbox works; carrying between phones does not yet. Apple only
allows this kind of peer link while the app is in the foreground, and it is
planned as a later version once the Android side has run for a while.

## Not yet: paying carriers

A carriage fee, where the phone that submits a letter keeps a slice of its
fee, is a chain change and is deliberately not in 0.14. It will be proposed as
a node 0.11 feature after carriage has been used in the wild.
