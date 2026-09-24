import 'dart:convert';
import 'dart:typed_data';

/// The plaintext of a letter: the same small JSON envelope every BerryChain
/// client uses, so a letter written on the phone reads the same on a PC or
/// through the MCP tools. Subject, threading and the display name sit inside
/// the encryption; the chain sees only addresses and sizes.
Uint8List composeLetter(String body, {String subject = '', String? replyTo, String senderName = ''}) {
  final env = <String, dynamic>{'v': 1, 'subject': subject, 'body': body};
  if (replyTo != null && replyTo.isNotEmpty) env['reply_to'] = replyTo;
  if (senderName.isNotEmpty) env['from_name'] = senderName;
  return Uint8List.fromList(utf8.encode(jsonEncode(env)));
}

class OpenedLetter {
  final String subject, body, fromName;
  final String? replyTo;
  final bool isHex;
  OpenedLetter(this.subject, this.body, this.fromName, this.replyTo, {this.isHex = false});
}

OpenedLetter openLetter(List<int> plaintext) {
  try {
    final text = utf8.decode(plaintext);
    try {
      final env = jsonDecode(text);
      if (env is Map && env['v'] == 1 && env['body'] is String) {
        return OpenedLetter((env['subject'] as String?) ?? '', env['body'] as String,
            (env['from_name'] as String?) ?? '', env['reply_to'] as String?);
      }
    } catch (_) {}
    return OpenedLetter('', text, '', null);
  } on FormatException {
    return OpenedLetter('', plaintext.map((b) => b.toRadixString(16).padLeft(2, '0')).join(), '', null, isHex: true);
  }
}
