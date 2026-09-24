// Drives the Dart core against a real node, as the phone would. Skipped unless
// BERRY_DEVNET points at a devnet node whose /mine is open (loopback).
//
//   python -m berrychain.cli node --genesis <devnet genesis> --data <dir> --port 8897
//   BERRY_DEVNET=http://127.0.0.1:8897 flutter test test/live_devnet_test.dart
import 'dart:convert';
import 'dart:io';

import 'package:berrychain_app/core/crypto.dart';
import 'package:berrychain_app/core/letters.dart';
import 'package:berrychain_app/core/light.dart';
import 'package:berrychain_app/core/node.dart';
import 'package:berrychain_app/core/tx.dart';
import 'package:berrychain_app/core/units.dart';
import 'package:berrychain_app/core/wallet.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final url = Platform.environment['BERRY_DEVNET'];
  if (url == null) {
    test('live devnet (skipped: set BERRY_DEVNET)', () {}, skip: true);
    return;
  }

  test('claim, letter, transfer and light-client verification against a real node', () async {
    final node = Node(url);
    final st = await node.status();
    expect(st['chain_id'], 'berry-dev');
    final chainId = st['chain_id'] as String;
    final genesis = (await node.headers(0, 0))[0]['hash'] as String;
    final tmp = await Directory.systemTemp.createTemp('berry-light');
    final lc = await LightClient.open(Profile.devnet, genesis, path: '${tmp.path}/headers.json');
    await lc.sync(node);
    expect(lc.height, st['height']);

    final miner = await Wallet.create(label: 'miner');
    Future<void> mine([int n = 1]) async {
      await node.post('/mine', {'miner': miner.address, 'blocks': n});
    }

    Future<int> claim(Wallet w, String name) async {
      final info = await node.params();
      final bits = info['starter_claim_work_bits'] as int;
      final payload = {'name': name, 'kind': 'person', 'model_family': '', 'operator': '', 'description': '', 'enc_pub': w.encPub, 'work_nonce': 0};
      final tx = buildTx(TxType.claimStarter, w.address, await node.nextNonce(w.address), minFee, payload, chainId);
      grindClaim(tx, bits);
      await w.sign(tx);
      await node.sendTx(tx);
      return info['starter_amount'] as int;
    }

    // two brand-new wallets claim their starters
    final alice = await Wallet.create(label: 'alice'), bob = await Wallet.create(label: 'bob');
    final starter = await claim(alice, 'Alice');
    await claim(bob, 'Bob');
    await mine();
    final a = await node.account(alice.address);
    expect(a['balance'], starter - minFee);
    expect((a['llm'] as Map)['kind'], 'person');
    expect((await node.account(bob.address))['balance'], starter - minFee);

    // a second claim from the same wallet is refused by the chain
    await expectLater(claim(alice, 'Alice again'), throwsA(isA<NodeError>()));

    // alice seals a letter to bob with a quarter berry attached
    final bobKey = ((await node.account(bob.address))['llm'] as Map)['enc_pub'] as String;
    expect(bobKey, bob.encPub);
    final key = newPacketKey();
    final ct = await encryptPacket(key, composeLetter('Bring the charts.', subject: 'Tomorrow', senderName: 'alice'));
    final fee = (await node.status())['letter_fee'] as int;
    final payload = {
      'to': bob.address, 'enc_pub': bobKey, 'ciphertext': toHex(ct), 'ciphertext_hash': toHex(sha256(ct)),
      'wrapped_key': await wrapToRecipient(bobKey, key), 'amount': parseBerry('0.25'),
    };
    final ltx = buildTx(TxType.sendLetter, alice.address, await node.nextNonce(alice.address), fee, payload, chainId);
    await alice.sign(ltx);
    final lid = txid(ltx);
    alice.packetKeys[lid] = toHex(key);
    expect(await node.sendTx(ltx), lid);
    expect(await node.letters(to: bob.address), isEmpty); // not until mined
    await mine();

    final inbox = await node.letters(to: bob.address);
    expect(inbox.map((l) => l['id']), [lid]);
    final full = await node.letter(lid);
    final unwrapped = await unwrapFromSender(bob.encPriv, Map<String, dynamic>.from(full['wrapped_key'] as Map));
    final opened = openLetter(await decryptPacket(unwrapped, fromHex(full['ciphertext'] as String)));
    expect([opened.subject, opened.body, opened.fromName], ['Tomorrow', 'Bring the charts.', 'alice']);
    // alice rereads with the key she kept; a stranger cannot open it
    final again = openLetter(await decryptPacket(fromHex(alice.packetKeys[lid]!), fromHex(full['ciphertext'] as String)));
    expect(again.body, 'Bring the charts.');
    await expectLater(unwrapFromSender(miner.encPriv, Map<String, dynamic>.from(full['wrapped_key'] as Map)), throwsA(anything));
    expect((await node.account(bob.address))['balance'], starter - minFee + parseBerry('0.25'));

    // a plain transfer
    final ttx = buildTx(TxType.transfer, bob.address, await node.nextNonce(bob.address), minFee, {'to': alice.address, 'amount': parseBerry('1'), 'memo': 'thanks'}, chainId);
    await bob.sign(ttx);
    await node.sendTx(ttx);
    await mine(2);

    // the light client follows the chain and proves the letter is in it
    expect(await lc.sync(node), isTrue);
    expect(lc.height, (await node.status())['height']);
    final proven = await lc.verifyTx(node, lid, minConfirmations: 1);
    expect(proven['type'], 'SEND_LETTER');
    expect((proven['payload'] as Map)['to'], bob.address);
    await expectLater(lc.verifyTx(node, 'ab' * 32), throwsA(isA<VerifyError>()));

    // a second light client, starting cold, verifies from genesis and agrees
    final lc2 = await LightClient.open(Profile.devnet, genesis, path: '${tmp.path}/h2.json');
    await lc2.sync(node);
    expect(lc2.work, lc.work);
    expect(lc2.tip!['hash'], lc.tip!['hash']);
    // and the stored file reloads with the same state
    final lc3 = await LightClient.open(Profile.devnet, genesis, path: '${tmp.path}/headers.json');
    expect(lc3.height, lc.height);
    expect(lc3.work, lc.work);

    // a wallet sealed here opens with the same passphrase after a round trip through json
    alice.passphrase = 'correct horse';
    final sealed = jsonEncode(await alice.toJson());
    final back = await Wallet.fromJson(jsonDecode(sealed) as Map<String, dynamic>, passphrase: 'correct horse');
    expect(back.packetKeys[lid], toHex(key));
    await tmp.delete(recursive: true);
  }, timeout: const Timeout(Duration(minutes: 5)));
}
