import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../core/letters.dart';
import '../core/photo.dart';
import '../core/crypto.dart';
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
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Letters'),
          bottom: TabBar(
            indicatorColor: Palette.gold,
            labelColor: Colors.white,
            unselectedLabelColor: const Color(0xFFA9BACC),
            tabs: [
              const Tab(text: 'Inbox'),
              const Tab(text: 'Sent'),
              ListenableBuilder(listenable: s, builder: (_, __) => Tab(text: s.drafts.isEmpty ? 'Drafts' : 'Drafts (${s.drafts.length})')),
            ],
          ),
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
            const _DraftList(),
          ]),
        ),
      ),
    );
  }
}

/// Removes a letter from this phone after saying plainly what that means.
Future<void> confirmRemove(BuildContext context, LetterItem l) async {
  final s = SessionScope.of(context);
  final ok = await showDialog<bool>(
    context: context,
    builder: (_) => AlertDialog(
      title: const Text('Remove this letter?'),
      content: const Text('It disappears from this phone. The sealed copy stays on the chain, as every letter does, and only the key that opens it could ever read it. '
          'You can show removed letters again from Settings.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
        FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Remove')),
      ],
    ),
  );
  if (ok == true) {
    await s.removeLetter(l.id);
    if (context.mounted) toast(context, 'Removed from this phone');
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
                final removed = s.isRemoved(l.id);
                return ListTile(
                  leading: Icon(incoming ? Icons.mail_outline : Icons.send_outlined, color: removed ? const Color(0xFF9A8D94) : Palette.brass),
                  title: Text(title, style: TextStyle(fontFamily: title == shortAddress(other) ? 'monospace' : null, color: removed ? const Color(0xFF9A8D94) : null)),
                  subtitle: Text('${removed ? 'removed · ' : ''}block ${l.height} · ${l.size} bytes${l.amount > 0 ? ' · +${formatBerry(l.amount)} BERRY${l.verified ? ' ✓' : ''}' : ''}'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ReadLetterScreen(l, incoming: incoming))),
                  onLongPress: () => removed ? s.restoreLetter(l.id) : confirmRemove(context, l),
                );
              },
            ),
    );
  }
}

class _DraftList extends StatelessWidget {
  const _DraftList();

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final drafts = s.drafts;
    if (drafts.isEmpty) {
      return ListView(children: const [Padding(padding: EdgeInsets.all(32), child: Text('No drafts. A letter you start and leave is kept here until you send or discard it.', textAlign: TextAlign.center, style: TextStyle(color: Color(0xFF6F7883))))]);
    }
    return ListView.builder(
      itemCount: drafts.length,
      itemBuilder: (context, i) {
        final d = drafts[i];
        final g = s.groupById(d.groupId);
        final who = g != null ? 'To group ${g.name}' : d.to.isEmpty ? 'No address yet' : 'To ${shortAddress(d.to)}';
        final when = DateTime.fromMillisecondsSinceEpoch(d.updated);
        return Dismissible(
          key: ValueKey(d.id),
          direction: DismissDirection.endToStart,
          background: Container(color: Palette.band, alignment: Alignment.centerRight, padding: const EdgeInsets.only(right: 20), child: const Icon(Icons.delete_outline, color: Colors.white)),
          onDismissed: (_) => s.deleteDraft(d.id),
          child: ListTile(
            leading: const Icon(Icons.drafts_outlined, color: Palette.brass),
            title: Text(d.subject.isNotEmpty ? d.subject : (d.body.trim().isNotEmpty ? d.body.trim().split('\n').first : 'Untitled draft'), maxLines: 1, overflow: TextOverflow.ellipsis),
            subtitle: Text('$who · ${when.day}/${when.month} ${when.hour.toString().padLeft(2, '0')}:${when.minute.toString().padLeft(2, '0')}${d.photoB64 != null ? ' · picture' : ''}'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ComposeScreen(draft: d))),
          ),
        );
      },
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
    final s = SessionScope.of(context);
    s.readLetter(widget.letter).then((o) async {
      if (!mounted) return;
      setState(() => opened = o);
      final g = o.group;
      if (g != null && widget.incoming) {
        final added = await s.adoptGroup(g, widget.letter.from);
        if (added && mounted) toast(context, 'Group "${g.name}" saved to People so you can reply to everyone');
      }
    }).catchError((e) {
      if (mounted) setState(() => error = '$e');
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final l = widget.letter;
    final o = opened;
    final group = o?.group == null ? null : (s.groupById(o!.group!.id) ?? o.group);
    return Scaffold(
      appBar: AppBar(
        title: Text(o?.subject.isNotEmpty == true ? o!.subject : 'Letter'),
        actions: [
          IconButton(
            icon: Icon(s.isRemoved(l.id) ? Icons.restore_from_trash_outlined : Icons.delete_outline),
            tooltip: s.isRemoved(l.id) ? 'Put back' : 'Remove from this phone',
            onPressed: () async {
              if (s.isRemoved(l.id)) {
                await s.restoreLetter(l.id);
              } else {
                await confirmRemove(context, l);
                if (context.mounted && s.isRemoved(l.id)) Navigator.pop(context);
              }
            },
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text('${widget.incoming ? 'From' : 'To'}: ${widget.incoming ? l.from : l.to}${o?.fromName.isNotEmpty == true ? '  (${o!.fromName})' : ''}', style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
          if (group != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text('Sent to the group "${group.name}" (${group.members.length + 1} people, including you)', style: const TextStyle(color: Palette.brass, fontSize: 13, fontWeight: FontWeight.w600)),
            ),
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
              label: Text(group != null ? 'Reply to ${o.fromName.isNotEmpty ? o.fromName : 'the sender'} only' : 'Reply'),
              onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ComposeScreen(to: l.from, subject: o.subject.startsWith('Re:') ? o.subject : 'Re: ${o.subject}', replyTo: l.id))),
            ),
            if (group != null) ...[
              const SizedBox(height: 10),
              FilledButton.icon(
                icon: const Icon(Icons.reply_all),
                label: Text('Reply to the group (${group.members.length} people)'),
                onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ComposeScreen(group: s.groupById(group.id) ?? group, subject: o.subject.startsWith('Re:') ? o.subject : 'Re: ${o.subject}', replyTo: l.id))),
              ),
            ],
          ],
        ],
      ),
    );
  }
}

class ComposeScreen extends StatefulWidget {
  final String? to, subject, replyTo;
  final LetterGroup? group;
  final Draft? draft;
  const ComposeScreen({super.key, this.to, this.subject, this.replyTo, this.group, this.draft});
  @override
  State<ComposeScreen> createState() => _ComposeScreenState();
}

class _ComposeScreenState extends State<ComposeScreen> {
  late final TextEditingController to, subject, body;
  final amount = TextEditingController();
  late final String draftId;
  String? replyTo;
  LetterGroup? group;
  Uint8List? photo;
  String? toName;
  bool toValid = false, sent = false;
  Timer? _autosave;

  @override
  void initState() {
    super.initState();
    final s = SessionScope.of(context);
    final d = widget.draft;
    draftId = d?.id ?? '${DateTime.now().millisecondsSinceEpoch}-${identityHashCode(this)}';
    to = TextEditingController(text: d?.to ?? widget.to ?? '');
    subject = TextEditingController(text: d?.subject ?? widget.subject ?? '');
    body = TextEditingController(text: d?.body ?? '');
    replyTo = d?.replyTo ?? widget.replyTo;
    group = widget.group ?? s.groupById(d?.groupId);
    if (d?.photoB64 != null) {
      try {
        photo = base64Decode(d!.photoB64!);
      } catch (_) {}
    }
    for (final c in [to, subject, body]) {
      c.addListener(_changed);
    }
    to.addListener(() => lookup(to.text.trim()));
    if (to.text.isNotEmpty) lookup(to.text.trim());
  }

  @override
  void dispose() {
    _autosave?.cancel();
    if (!sent) _saveNow();
    super.dispose();
  }

  void _changed() {
    setState(() {});
    _autosave?.cancel();
    _autosave = Timer(const Duration(seconds: 2), _saveNow);
  }

  Future<void> _saveNow() async {
    if (sent) return;
    final s = SessionScope.of(context);
    await s.saveDraft(Draft(draftId,
        to: group == null ? to.text.trim() : '', subject: subject.text, body: body.text, replyTo: replyTo, groupId: group?.id, photoB64: photo == null ? null : base64Encode(photo!)));
  }

  Future<void> lookup(String addr) async {
    final valid = isValidAddress(addr);
    if (mounted) {
      setState(() {
        toValid = valid;
        toName = null;
      });
    }
    if (!valid) return;
    final n = await SessionScope.of(context).lookupName(addr);
    if (mounted && to.text.trim() == addr) setState(() => toName = n);
  }

  Future<void> takePhoto(ImageSource source) async {
    final picked = await ImagePicker().pickImage(source: source, maxWidth: 1200, maxHeight: 1200, imageQuality: 85);
    if (picked == null || !mounted) return;
    final raw = await picked.readAsBytes();
    if (!mounted) return;
    final small = await runBusy<Uint8List>(context, 'Shrinking the picture to fit the envelope…', () => compute(shrinkPhotoInIsolate, shrinkPhotoArgs(raw, 400, 18 * 1024)));
    if (small != null) {
      setState(() => photo = small);
      _changed();
    }
  }

  Future<void> discard() async {
    final s = SessionScope.of(context);
    sent = true; // do not re-save on dispose
    await s.deleteDraft(draftId);
    if (mounted) Navigator.pop(context);
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
    final g = group;
    if (g != null) {
      final n = g.members.where((m) => m != s.wallet!.address).length;
      final fee = s.letterFee ?? minFee;
      final ok = await showDialog<bool>(
        context: context,
        builder: (_) => AlertDialog(
          title: Text('Send to ${g.name}?'),
          content: Text('One sealed copy to each of $n people. Fees ${formatBerry(n * fee)} BERRY${seeds > 0 ? ', plus ${formatBerry(seeds)} BERRY to each' : ''}.'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Send')),
          ],
        ),
      );
      if (ok != true || !mounted) return;
    }
    final result = await runBusy(context, g == null ? 'Sealing and sending…' : 'Sealing ${g.members.length} copies and sending…', () async {
      if (g != null) return s.sendGroupLetter(g, subject.text.trim(), body.text, seeds, replyTo: replyTo, photoJpeg: photo);
      return s.sendLetter(to.text.trim(), subject.text.trim(), body.text, seeds, replyTo: replyTo, photoJpeg: photo);
    });
    if (result != null && mounted) {
      sent = true;
      await s.deleteDraft(draftId);
      if (!mounted) return;
      toast(context, g == null ? 'Sealed and sent. Readable once the block is mined.' : 'Sealed and sent to everyone in ${g.name}.');
      s.refresh();
      Navigator.pop(context);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final g = group;
    final budget = textBudget(photoJpeg: photo, group: g);
    final used = composeLetter(body.text, subject: subject.text, replyTo: replyTo, senderName: s.wallet!.label, group: g).length - composeLetter('', group: g).length;
    final left = budget - used;
    final fee = s.letterFee ?? minFee;
    final copies = g == null ? 1 : g.members.where((m) => m != s.wallet!.address).length;
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.draft != null ? 'Draft' : 'Write a letter'),
        actions: [
          IconButton(icon: const Icon(Icons.photo_camera_outlined), tooltip: 'Take a picture', onPressed: photo == null ? () => takePhoto(ImageSource.camera) : null),
          IconButton(icon: const Icon(Icons.photo_library_outlined), tooltip: 'Picture from gallery', onPressed: photo == null ? () => takePhoto(ImageSource.gallery) : null),
          IconButton(icon: const Icon(Icons.delete_outline), tooltip: 'Discard draft', onPressed: discard),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          if (g != null)
            InputDecorator(
              decoration: InputDecoration(
                labelText: 'To group',
                suffixIcon: IconButton(icon: const Icon(Icons.close), tooltip: 'Write to one person instead', onPressed: () => setState(() => group = null)),
              ),
              child: Wrap(
                spacing: 6,
                runSpacing: -6,
                children: [
                  Chip(avatar: const Icon(Icons.groups_outlined, size: 18), label: Text(g.name, style: const TextStyle(fontWeight: FontWeight.w600))),
                  for (final m in g.members.where((m) => m != s.wallet!.address))
                    Chip(label: Text(s.contacts.where((c) => c.address == m).map((c) => c.label).firstOrNull ?? shortAddress(m), style: const TextStyle(fontSize: 12.5))),
                ],
              ),
            )
          else ...[
            TextField(
              controller: to,
              decoration: InputDecoration(
                labelText: 'To (brry1…)',
                suffixIcon: IconButton(
                  icon: const Icon(Icons.people_outline),
                  tooltip: 'Choose from your people or groups',
                  onPressed: () async {
                    final picked = await pickRecipient(context);
                    if (picked is Contact) setState(() => to.text = picked.address);
                    if (picked is LetterGroup) {
                      setState(() {
                        group = picked;
                        to.text = '';
                      });
                      _changed();
                    }
                  },
                ),
              ),
              autocorrect: false,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 13),
            ),
            if (to.text.trim().isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(
                  !toValid ? 'Not a BerryChain address yet' : toName == null ? 'Looking up…' : toName!.isEmpty ? 'This address has no registered name; check it carefully' : 'Sending to $toName',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: !toValid ? Palette.band : (toName?.isNotEmpty == true ? Palette.leaf : const Color(0xFF6F7883))),
                ),
              ),
          ],
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
                IconButton.filled(
                    icon: const Icon(Icons.close),
                    onPressed: () {
                      setState(() => photo = null);
                      _changed();
                    }),
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
          TextField(controller: amount, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: InputDecoration(labelText: g == null ? 'BERRY to send with it (optional)' : 'BERRY to send with each copy (optional)')),
          const SizedBox(height: 16),
          FilledButton.icon(icon: const Icon(Icons.lock_outline), label: Text(g == null ? 'Seal and send' : 'Seal and send to $copies people'), onPressed: left < 0 ? null : send),
          const SizedBox(height: 12),
          Text(
            g == null
                ? 'Fee ${formatBerry(fee)} BERRY. Only the recipient can read this; the ledger shows the two addresses, the time and the size. Drafts are kept on this phone until you send or discard them.'
                : 'One sealed copy per person, ${formatBerry(fee)} BERRY each. Each copy carries the group so they can reply to everyone. The ledger shows you writing to $copies addresses.',
            style: const TextStyle(color: Color(0xFF6F7883), fontSize: 13),
          ),
        ],
      ),
    );
  }
}
