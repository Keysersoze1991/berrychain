import 'dart:convert';

import 'parcels.dart';
import 'dart:typed_data';

/// The plaintext of a letter: the same small JSON envelope every BerryChain
/// client uses, so a letter written on the phone reads the same on a PC or
/// through the MCP tools. Subject, threading, the display name, an optional
/// small picture and, for a letter sent to several people at once, the group
/// it went to all sit inside the encryption; the chain sees only addresses
/// and sizes.
const envelopeLimit = 32 * 1024; // MAX_PACKET_INLINE_BYTES on the chain
const _sealOverhead = 12 + 16; // nonce and tag added by the content encryption

/// A named set of addresses a letter goes to at once. Kept on the phone, and
/// carried inside each copy of a group letter so the other members' apps can
/// recreate it and reply to everyone.
class LetterGroup {
  final String id, name;
  final List<String> members;
  LetterGroup(this.id, this.name, this.members);

  Map<String, dynamic> toJson() => {'id': id, 'name': name, 'members': members};

  static LetterGroup? fromJson(dynamic j) {
    if (j is! Map || j['id'] is! String || j['name'] is! String || j['members'] is! List) return null;
    final members = (j['members'] as List).whereType<String>().toList();
    if (members.isEmpty) return null;
    return LetterGroup(j['id'] as String, j['name'] as String, members);
  }
}

Uint8List composeLetter(String body, {String subject = '', String? replyTo, String senderName = '', Uint8List? photoJpeg, LetterGroup? group, ParcelRef? parcel}) {
  final env = <String, dynamic>{'v': 1, 'subject': subject, 'body': body};
  if (replyTo != null && replyTo.isNotEmpty) env['reply_to'] = replyTo;
  if (senderName.isNotEmpty) env['from_name'] = senderName;
  if (photoJpeg != null && photoJpeg.isNotEmpty) env['photo_jpeg_b64'] = base64Encode(photoJpeg);
  if (group != null) env['group'] = group.toJson();
  if (parcel != null) env['parcel'] = parcel.toJson();
  return Uint8List.fromList(utf8.encode(jsonEncode(env)));
}

/// Bytes still free for text once [photoJpeg] is attached, so the writer can
/// see the budget before sealing. Negative means the photo alone is too big.
int textBudget({Uint8List? photoJpeg, LetterGroup? group, ParcelRef? parcel}) {
  final base = composeLetter('', photoJpeg: photoJpeg, group: group, parcel: parcel).length;
  return envelopeLimit - _sealOverhead - base;
}

bool fitsEnvelope(Uint8List plaintext) => plaintext.length + _sealOverhead <= envelopeLimit;

class OpenedLetter {
  final String subject, body, fromName;
  final String? replyTo;
  final Uint8List? photoJpeg;
  final LetterGroup? group;
  final ParcelRef? parcel;
  final bool isHex;
  OpenedLetter(this.subject, this.body, this.fromName, this.replyTo, {this.photoJpeg, this.group, this.parcel, this.isHex = false});
}

OpenedLetter openLetter(List<int> plaintext) {
  try {
    final text = utf8.decode(plaintext);
    try {
      final env = jsonDecode(text);
      if (env is Map && env['v'] == 1 && env['body'] is String) {
        Uint8List? photo;
        if (env['photo_jpeg_b64'] is String) {
          try {
            photo = base64Decode(env['photo_jpeg_b64'] as String);
          } catch (_) {}
        }
        return OpenedLetter((env['subject'] as String?) ?? '', env['body'] as String,
            (env['from_name'] as String?) ?? '', env['reply_to'] as String?, photoJpeg: photo, group: LetterGroup.fromJson(env['group']), parcel: ParcelRef.fromJson(env['parcel']));
      }
    } catch (_) {}
    return OpenedLetter('', text, '', null);
  } on FormatException {
    return OpenedLetter('', plaintext.map((b) => b.toRadixString(16).padLeft(2, '0')).join(), '', null, isHex: true);
  }
}
