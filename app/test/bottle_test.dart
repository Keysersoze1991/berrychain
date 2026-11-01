import 'dart:typed_data';

import 'package:berrychain_app/core/bottle.dart';
import 'package:berrychain_app/core/crypto.dart';
import 'package:berrychain_app/core/outbox.dart';
import 'package:berrychain_app/core/wallet.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late Wallet alice, bob;
  setUpAll(() async {
    alice = await Wallet.create(label: 'Alice');
    bob = await Wallet.create(label: 'Bob');
  });

  test('a bottle seals, verifies, opens for the recipient and rereads for the sender', () async {
    final (note, key) = await Bottle.seal(
        from: alice.address, signPriv: alice.signPriv, signPub: alice.signPub, senderName: 'Alice',
        to: bob.address, toEncPub: bob.encPub, subject: 'Ahoy', body: 'Meet at the jetty at six.');
    expect(note['kind'], 'bottle');
    expect(note['id'], Bottle.idOf(note));
    expect(await Bottle.verify(note), isTrue);
    final forBob = await Bottle.open(note, recipientEncPriv: bob.encPriv);
    expect(forBob.subject, 'Ahoy');
    expect(forBob.body, 'Meet at the jetty at six.');
    expect(forBob.fromName, 'Alice');
    final forAlice = await Bottle.open(note, packetKey: key);
    expect(forAlice.body, forBob.body);
  });

  test('a tampered or re-addressed note is refused', () async {
    final (note, _) = await Bottle.seal(
        from: alice.address, signPriv: alice.signPriv, signPub: alice.signPub, senderName: 'Alice',
        to: bob.address, toEncPub: bob.encPub, subject: '', body: 'secret');
    final bent = Map<String, dynamic>.from(note)..['to'] = alice.address;
    expect(await Bottle.verify(bent), isFalse);                       // signature no longer matches
    final forged = Map<String, dynamic>.from(note)..['from'] = bob.address;
    expect(await Bottle.verify(forged), isFalse);                     // pubkey does not match the claimed sender
    final swapped = Map<String, dynamic>.from(note)..['ciphertext'] = toHex(Uint8List.fromList(List.filled(64, 7)));
    expect(await Bottle.verify(swapped), isFalse);                    // hash mismatch
    final stale = Map<String, dynamic>.from(note)..['created'] = (note['created'] as int) - Bottle.ttlSeconds - 10;
    expect(await Bottle.verify(stale), isFalse);                      // and anyway the signature breaks
  });

  test('receipts verify and name the note they answer', () async {
    final (note, _) = await Bottle.seal(
        from: alice.address, signPriv: alice.signPriv, signPub: alice.signPub, senderName: 'Alice',
        to: bob.address, toEncPub: bob.encPub, subject: '', body: 'ping');
    final ack = await Bottle.ack(noteId: note['id'] as String, from: bob.address, to: alice.address, signPriv: bob.signPriv, signPub: bob.signPub);
    expect(ack['kind'], 'bottle_ack');
    expect(ack['note'], note['id']);
    expect(await Bottle.verify(ack), isTrue);
  });

  test('the outbox carries notes once, prunes stale ones, and keeps its own', () async {
    final box = Outbox();
    final (note, _) = await Bottle.seal(
        from: alice.address, signPriv: alice.signPriv, signPub: alice.signPub, senderName: 'Alice',
        to: bob.address, toEncPub: bob.encPub, subject: '', body: 'carry me');
    await box.addNote(note, hops: 2);
    await box.addNote(note, hops: 5);
    expect(box.notes.length, 1);
    expect(box.carriedNotes, 1);
    expect(box.notesWire().first['hops'], 2);
    box.notes.first['created'] = 1;                                     // long ago
    box.prune();
    expect(box.notes, isEmpty);
    await box.addNote(note, mine: true);
    expect(box.carriedNotes, 0);
    await box.removeNote(note['id'] as String);
    expect(box.hasNote(note['id'] as String), isFalse);
  });
}
