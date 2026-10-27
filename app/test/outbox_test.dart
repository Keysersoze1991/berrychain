import 'dart:convert';

import 'package:berrychain_app/core/outbox.dart';
import 'package:berrychain_app/core/tx.dart';
import 'package:flutter_test/flutter_test.dart';

final String addrA = 'brry1${'ab' * 20}0123456789';
final String addrB = 'brry1${'cd' * 20}0123456789';

Map<String, dynamic> fakeTx(int nonce, {String? from}) => {
      'type': 'send_letter', 'from': from ?? addrA, 'nonce': nonce, 'fee': 1, 'chain_id': 'berry-1',
      'payload': {'to': addrB, 'ciphertext': 'ff'},
      'sig': 'a' * 128, 'pubkey': 'b' * 64,
    };

void main() {
  test('only well-formed signed transactions are accepted from a nearby phone', () async {
    final box = Outbox();
    expect(Outbox.looksLikeTx(fakeTx(1)), isTrue);
    expect(Outbox.looksLikeTx({...fakeTx(1)}..remove('sig')), isFalse);
    expect(Outbox.looksLikeTx({...fakeTx(1), 'from': 'nope'}), isFalse);
    final added = await box.fromWire([
      {'tx': fakeTx(1), 'hops': 0},
      {'tx': fakeTx(1), 'hops': 3},                 // the same letter twice: once
      {'tx': {'junk': true}, 'hops': 0},            // not a transaction
      {'tx': fakeTx(2), 'hops': Outbox.maxHops},    // carried too far already
      'garbage',
    ]);
    expect(added, 1);
    expect(box.carriedCount, 1);
    expect(box.items.first.hops, 1);
    expect(box.items.first.id, txid(fakeTx(1)));
  });

  test('the wire form round-trips and a phone never hands a letter back to itself', () async {
    final a = Outbox(), b = Outbox();
    await a.fromWire([{'tx': fakeTx(5), 'hops': 0}]);
    final wire = jsonDecode(jsonEncode(a.toWire())) as List;
    expect(await b.fromWire(wire), 1);
    expect(await a.fromWire(jsonDecode(jsonEncode(b.toWire())) as List), 0);
    expect(b.items.first.hops, 2);
  });

  test('carried items are pruned before our own when the box is full', () async {
    final box = Outbox();
    for (var i = 0; i < Outbox.maxItems + 5; i++) {
      box.items.add(OutboxItem(id: 'c$i', tx: fakeTx(i), mine: false, created: DateTime.now().millisecondsSinceEpoch ~/ 1000));
    }
    box.items.add(OutboxItem(id: 'mine', tx: fakeTx(999), mine: true, created: DateTime.now().millisecondsSinceEpoch ~/ 1000));
    box.prune();
    expect(box.items.length, Outbox.maxItems);
    expect(box.mineCount, 1);
  });
}
