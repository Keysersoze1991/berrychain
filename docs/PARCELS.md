# Parcels: large attachments beside the chain

A letter's sealed envelope is capped at 32 KB on the chain, enough for words
and one small picture. Anything bigger goes through a **parcel room**, a
service beside a seed node that keeps sealed blobs for a while and hands
them to the letter's recipient. The chain carries only the letter, with the
parcel's key and hash inside the seal.

## What happens when someone attaches a file

1. The app seals the file with a fresh packet key (the same cipher letters
   use), hashes the ciphertext, and shows the price.
2. It pays the room's address `price(size)` BERRY in an ordinary transfer
   whose memo is `parcel:<hash>`.
3. It uploads the ciphertext to `POST /parcels/<hash>`. The room stores it
   at once and marks it paid when the transfer is in a block (an upload may
   wait up to fifteen minutes for its payment, then it is dropped).
4. The letter is sent as usual, carrying `{hash, key, size, name, room}`
   inside its seal. The room never sees the key.
5. The recipient's app fetches `GET /parcels/<hash>`, checks the hash, and
   opens the blob with the key from the letter. Parcels are kept for
   `PARCEL_TTL_DAYS` (30), then deleted. The payer can delete one early with
   a signed `DELETE` (burning a letter does this).

The room learns the payer's address, the hash and the size: no file name,
no content, no recipient.

## Price

`PARCEL_PRICE_SEEDS` per started `PARCEL_CHUNK_BYTES`: 1 BERRY per 100 MB,
with a 100 MB cap, so in practice a parcel costs one berry. Paid to `PARCEL_ADDRESS`, chosen by the
operator; on seed1 it is the network-operations wallet, so parcels pay for
the disk they occupy. Not a consensus rule: the operator can change it any
time and the app reads the current terms from `/parcels/status`.

## Running one (seed1)

```bash
# on seed1, as root; the address is where parcels are paid to
PARCEL_ADDRESS=brry1... bash /opt/berrychain/deploy/parcels-setup.sh
curl -s https://seed1.berrychain.link/parcels/status
```

`/parcels/status` answers `{parcels, paid, pending, bytes, served, max_bytes,
chunk_bytes, price_per_chunk, ttl_days, address, height}`. Disk use is
bounded: with a 100 MB cap and 30-day expiry, 40 GB holds about 400
parcels in flight. Watch `bytes` and add disk or a second room when it
climbs.

## From the command line

```bash
python -m berrychain.cli parcel status
python -m berrychain.cli parcel send keys/me.json brry1... holiday.zip --subject "Photos"
python -m berrychain.cli letter read keys/me.json LETTER_ID     # saves the parcel beside the letter
```

## Limits and honesty

- One room per letter: the reference names the room's URL. If that room is
  gone before the recipient fetches, the parcel is gone; the letter still
  opens.
- The room is a plain blob store. Anyone who learns a hash can download the
  ciphertext; without the key from the letter it is noise.
- Parcels are not on the chain and are not permanent; that is the point.
