import 'dart:typed_data';

import 'package:berrychain_app/core/blumail.dart';
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

  test('a BluMail note seals, verifies, opens for the recipient and rereads for the sender', () async {
    final (note, key) = await BluMail.seal(
        from: alice.address, signPriv: alice.signPriv, signPub: alice.signPub, senderName: 'Alice',
        to: bob.address, toEncPub: bob.encPub, subject: 'Ahoy', body: 'Meet at the jetty at six.');
    expect(note['kind'], 'blumail');
    expect(note['id'], BluMail.idOf(note));
    expect(await BluMail.verify(note), isTrue);
    final forBob = await BluMail.open(note, recipientEncPriv: bob.encPriv);
    expect(forBob.subject, 'Ahoy');
    expect(forBob.body, 'Meet at the jetty at six.');
    expect(forBob.fromName, 'Alice');
    final forAlice = await BluMail.open(note, packetKey: key);
    expect(forAlice.body, forBob.body);
  });

  test('a tampered or re-addressed note is refused', () async {
    final (note, _) = await BluMail.seal(
        from: alice.address, signPriv: alice.signPriv, signPub: alice.signPub, senderName: 'Alice',
        to: bob.address, toEncPub: bob.encPub, subject: '', body: 'secret');
    final bent = Map<String, dynamic>.from(note)..['to'] = alice.address;
    expect(await BluMail.verify(bent), isFalse);                       // signature no longer matches
    final forged = Map<String, dynamic>.from(note)..['from'] = bob.address;
    expect(await BluMail.verify(forged), isFalse);                     // pubkey does not match the claimed sender
    final swapped = Map<String, dynamic>.from(note)..['ciphertext'] = toHex(Uint8List.fromList(List.filled(64, 7)));
    expect(await BluMail.verify(swapped), isFalse);                    // hash mismatch
    final stale = Map<String, dynamic>.from(note)..['created'] = (note['created'] as int) - BluMail.ttlSeconds - 10;
    expect(await BluMail.verify(stale), isFalse);                      // and anyway the signature breaks
  });

  test('receipts verify and name the note they answer', () async {
    final (note, _) = await BluMail.seal(
        from: alice.address, signPriv: alice.signPriv, signPub: alice.signPub, senderName: 'Alice',
        to: bob.address, toEncPub: bob.encPub, subject: '', body: 'ping');
    final ack = await BluMail.ack(noteId: note['id'] as String, from: bob.address, to: alice.address, signPriv: bob.signPriv, signPub: bob.signPub);
    expect(ack['kind'], 'bluack');
    expect(ack['note'], note['id']);
    expect(await BluMail.verify(ack), isTrue);
  });

  test('the outbox carries notes once, prunes stale ones, and keeps its own', () async {
    final box = Outbox();
    final (note, _) = await BluMail.seal(
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
