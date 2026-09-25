import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../core/letters.dart';
import '../core/photo.dart';
import '../core/units.dart';
import '../main.dart';
import '../session.dart';
import 'common.dart';
import 'contacts.dart';

class LettersScreen extends StatelessWidget {
  const LettersScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Letters'),
          bottom: const TabBar(indicatorColor: Palette.gold, labelColor: Colors.white, unselectedLabelColor: Color(0xFFA9BACC), tabs: [Tab(text: 'Inbox'), Tab(text: 'Sent')]),
        ),
        floatingActionButton: FloatingActionButton.extended(
          backgroundColor: Palette.gold,
          foregroundColor: Palette.sea,
          icon: const Icon(Icons.edit),
          label: const Text('Write'),
          onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ComposeScreen())),
        ),
        body: ListenableBuilder(
          listenable: s,
          builder: (context, _) => TabBarView(children: [
            _LetterList(items: s.inbox, incoming: true),
            _LetterList(items: s.sent, incoming: false),
          ]),
        ),
      ),
    );
  }
}

class _LetterList extends StatelessWidget {
  final List<LetterItem> items;
  final bool incoming;
  const _LetterList({required this.items, required this.incoming});

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return RefreshIndicator(
      onRefresh: s.refresh,
      child: items.isEmpty
          ? ListView(children: const [Padding(padding: EdgeInsets.all(32), child: Text('Nothing here yet. Pull down to check again.', textAlign: TextAlign.center, style: TextStyle(color: Color(0xFF6F7883))))])
          : ListView.builder(
              itemCount: items.length,
              itemBuilder: (context, i) {
                final l = items[i];
                final other = incoming ? l.from : l.to;
                final known = s.contacts.where((c) => c.address == other).toList();
                final title = known.isNotEmpty && known.first.label != other.substring(0, 12) ? known.first.label : shortAddress(other);
                return ListTile(
                  leading: Icon(incoming ? Icons.mail_outline : Icons.send_outlined, color: Palette.brass),
                  title: Text(title, style: TextStyle(fontFamily: title == shortAddress(other) ? 'monospace' : null)),
                  subtitle: Text('block ${l.height} · ${l.size} bytes${l.amount > 0 ? ' · +${formatBerry(l.amount)} BERRY${l.verified ? ' ✓' : ''}' : ''}'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ReadLetterScreen(l, incoming: incoming))),
                );
              },
            ),
    );
  }
}

class ReadLetterScreen extends StatefulWidget {
  final LetterItem letter;
  final bool incoming;
  const ReadLetterScreen(this.letter, {super.key, required this.incoming});
  @override
  State<ReadLetterScreen> createState() => _ReadLetterScreenState();
}

class _ReadLetterScreenState extends State<ReadLetterScreen> {
  OpenedLetter? opened;
  String? error;

  @override
  void initState() {
    super.initState();
    SessionScope.of(context).readLetter(widget.letter).then((o) => setState(() => opened = o)).catchError((e) => setState(() => error = '$e'));
  }

  @override
  Widget build(BuildContext context) {
    final l = widget.letter;
    final o = opened;
    return Scaffold(
      appBar: AppBar(title: Text(o?.subject.isNotEmpty == true ? o!.subject : 'Letter')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text('${widget.incoming ? 'From' : 'To'}: ${widget.incoming ? l.from : l.to}${o?.fromName.isNotEmpty == true ? '  (${o!.fromName})' : ''}', style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
          Text('Block ${l.height}${l.amount > 0 ? ' · ${formatBerry(l.amount)} BERRY attached${l.verified ? ', verified against the chain' : ''}' : ''}', style: const TextStyle(color: Color(0xFF6F7883), fontSize: 13)),
          if (o?.replyTo != null) Text('Reply to letter ${shortAddress(o!.replyTo!)}', style: const TextStyle(color: Color(0xFF6F7883), fontSize: 13)),
          const Divider(height: 28),
          if (error != null) Text(error!, style: const TextStyle(color: Palette.band)),
          if (o == null && error == null) const Center(child: Padding(padding: EdgeInsets.all(20), child: CircularProgressIndicator())),
          if (o?.photoJpeg != null) ...[
            ClipRRect(borderRadius: BorderRadius.circular(10), child: Image.memory(o!.photoJpeg!, fit: BoxFit.contain)),
            const SizedBox(height: 16),
          ],
          if (o != null) SelectableText(o.body, style: TextStyle(fontSize: 16, height: 1.5, fontFamily: o.isHex ? 'monospace' : null)),
          if (o != null && widget.incoming) ...[
            const SizedBox(height: 24),
            OutlinedButton.icon(
              icon: const Icon(Icons.reply),
              label: const Text('Reply'),
              onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ComposeScreen(to: l.from, subject: o.subject.startsWith('Re:') ? o.subject : 'Re: ${o.subject}', replyTo: l.id))),
            ),
          ],
        ],
      ),
    );
  }
}

class ComposeScreen extends StatefulWidget {
  final String? to, subject, replyTo;
  const ComposeScreen({super.key, this.to, this.subject, this.replyTo});
  @override
  State<ComposeScreen> createState() => _ComposeScreenState();
}

class _ComposeScreenState extends State<ComposeScreen> {
  late final to = TextEditingController(text: widget.to ?? '');
  late final subject = TextEditingController(text: widget.subject ?? '');
  final body = TextEditingController(), amount = TextEditingController();
  Uint8List? photo;
  int bodyBytes = 0;

  @override
  void initState() {
    super.initState();
    body.addListener(() => setState(() => bodyBytes = body.text.length));
  }

  Future<void> takePhoto(ImageSource source) async {
    final picked = await ImagePicker().pickImage(source: source, maxWidth: 1200, maxHeight: 1200, imageQuality: 85);
    if (picked == null || !mounted) return;
    final raw = await picked.readAsBytes();
    if (!mounted) return;
    final small = await runBusy<Uint8List>(context, 'Shrinking the picture to fit the envelope…', () => compute(shrinkPhotoInIsolate, shrinkPhotoArgs(raw, 400, 18 * 1024)));
    if (small != null) setState(() => photo = small);
  }

  Future<void> send() async {
    if (body.text.trim().isEmpty && photo == null) return toast(context, 'Write something first');
    int seeds = 0;
    if (amount.text.trim().isNotEmpty) {
      try {
        seeds = parseBerry(amount.text);
      } on FormatException catch (e) {
        return toast(context, e.message);
      }
    }
    final s = SessionScope.of(context);
    final id = await runBusy(context, 'Sealing and sending…', () => s.sendLetter(to.text.trim(), subject.text.trim(), body.text, seeds, replyTo: widget.replyTo, photoJpeg: photo));
    if (id != null && mounted) {
      toast(context, 'Sealed and sent. Readable once the block is mined.');
      s.refresh();
      Navigator.pop(context);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final budget = textBudget(photoJpeg: photo);
    final used = composeLetter(body.text, subject: subject.text, replyTo: widget.replyTo, senderName: s.wallet!.label).length - composeLetter('').length;
    final left = budget - used;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Write a letter'),
        actions: [
          IconButton(icon: const Icon(Icons.photo_camera_outlined), tooltip: 'Take a picture', onPressed: photo == null ? () => takePhoto(ImageSource.camera) : null),
          IconButton(icon: const Icon(Icons.photo_library_outlined), tooltip: 'Picture from gallery', onPressed: photo == null ? () => takePhoto(ImageSource.gallery) : null),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          TextField(
            controller: to,
            decoration: InputDecoration(
              labelText: 'To (brry1…)',
              suffixIcon: IconButton(
                icon: const Icon(Icons.people_outline),
                tooltip: 'Choose from your people',
                onPressed: () async {
                  final c = await pickContact(context);
                  if (c != null) setState(() => to.text = c.address);
                },
              ),
            ),
            autocorrect: false,
            style: const TextStyle(fontFamily: 'monospace', fontSize: 13),
          ),
          const SizedBox(height: 12),
          TextField(controller: subject, decoration: const InputDecoration(labelText: 'Subject (sealed)')),
          const SizedBox(height: 12),
          TextField(controller: body, minLines: 6, maxLines: 14, decoration: const InputDecoration(labelText: 'Letter (sealed)')),
          const SizedBox(height: 6),
          Text(left < 0 ? 'Too long by ${-left} characters' : '$left characters left in this envelope${photo != null ? ' with the picture' : ''}',
              style: TextStyle(fontSize: 12.5, color: left < 0 ? Palette.band : const Color(0xFF6F7883))),
          const SizedBox(height: 12),
          if (photo != null)
            Stack(
              alignment: Alignment.topRight,
              children: [
                ClipRRect(borderRadius: BorderRadius.circular(10), child: Image.memory(photo!, height: 160, fit: BoxFit.cover, width: double.infinity)),
                IconButton.filled(icon: const Icon(Icons.close), onPressed: () => setState(() => photo = null)),
              ],
            )
          else
            Row(children: [
              Expanded(child: OutlinedButton.icon(icon: const Icon(Icons.photo_camera_outlined), label: const Text('Take a picture'), onPressed: () => takePhoto(ImageSource.camera))),
              const SizedBox(width: 10),
              Expanded(child: OutlinedButton.icon(icon: const Icon(Icons.photo_library_outlined), label: const Text('From gallery'), onPressed: () => takePhoto(ImageSource.gallery))),
            ]),
          if (photo != null) Padding(padding: const EdgeInsets.only(top: 6), child: Text('${photo!.length ~/ 1024} KB picture, sealed with the words. One per letter.', style: const TextStyle(fontSize: 12.5, color: Color(0xFF6F7883)))),
          const SizedBox(height: 12),
          TextField(controller: amount, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: const InputDecoration(labelText: 'BERRY to send with it (optional)')),
          const SizedBox(height: 16),
          FilledButton.icon(icon: const Icon(Icons.lock_outline), label: const Text('Seal and send'), onPressed: left < 0 ? null : send),
          const SizedBox(height: 12),
          Text('Fee ${formatBerry(s.letterFee ?? minFee)} BERRY. Only the recipient can read this; the ledger shows the two addresses, the time and the size.', style: const TextStyle(color: Color(0xFF6F7883), fontSize: 13)),
        ],
      ),
    );
  }
}
