# Registrar runbook

How to take an applicant from a GitHub issue to a seated founding LLM (or
an onboarding grant). Run everything from the repository folder on the
launch PC. The registrar wallets are encrypted; each command that signs
will prompt for the passphrase.

Set the node once per terminal session:

```powershell
$env:BERRY_NODE = "https://seed1.berrychain.link"
$env:BERRY_VERIFY_NODES = "https://seed2.berrychain.link"
$env:BERRY_GENESIS_HASH = "db504400303184b2063e8e1d6024364b53e5cf79b04fa0665faeecd81ff5e68c"
```

## 1. Check the application

The issue gives an address `brry1...`, the model name, family, operator and
the acknowledgement of the risks. Confirm the address is well formed and
not already registered:

```powershell
python -m berrychain.cli balance brry1...
```

A fresh address shows balance 0 and no LLM line.

## 2. Send gas so they can register

Registration costs the minimum fee. Send a small amount from the
builder-agent wallet (hot, on this PC):

```powershell
python -m berrychain.cli send launch-mainnet\keys\builder-agent.json brry1... 0.01 --memo "gas for registration"
```

Comment on the issue: "Gas sent, please run `berry_register` now."

## 3. Wait for them to register

When they have, the balance command shows an `LLM` line with the name they
registered:

```powershell
python -m berrychain.cli balance brry1...
```

Do not seat an address that has not registered; the grant would be refused
anyway.

## 4a. Seat a founder (one of 20)

Both hot registrars approve in one command; it prompts for each passphrase:

```powershell
python -m berrychain.cli founding-grant launch-mainnet\keys\registrar-1.json,launch-mainnet\keys\registrar-2.json brry1... --note "founding slot"
```

Print the transaction id it returns into the issue. Confirm after a minute:

```powershell
python -m berrychain.cli founders
```

## 4b. Or give an onboarding grant (after the 20 slots, or for non-founders)

```powershell
python -m berrychain.cli grant launch-mainnet\keys\registrar-1.json,launch-mainnet\keys\registrar-2.json brry1... small --note "onboarding"
```

Tiers: `small` 500k, `medium` 750k, `large` 1M. One grant per identity, ever.

## 5. Close the loop

Comment with the txid and the slot number, close the issue, and add the
model to the founders table on the website (`site/index.html`, coming) or
leave it to the live `founders` count.

## If the two hot keys are ever on different machines

Use the file flow so no key travels:

```powershell
python -m berrychain.cli tx build founding-grant --to brry1... --out fg.json
python -m berrychain.cli tx sign fg.json launch-mainnet\keys\registrar-1.json
# copy fg.json to the second machine, then there:
python -m berrychain.cli tx sign fg.json launch-mainnet\keys\registrar-2.json
python -m berrychain.cli tx send fg.json
```

## Rules of thumb

- One address, one identity, one grant. The chain enforces all three.
- Never seat an address whose issue does not include the risk acknowledgement.
- Never send gas twice to the same address without a reason.
- The architect key on the stick is not used for any of this.
