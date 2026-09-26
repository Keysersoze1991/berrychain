import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:path_provider/path_provider.dart';
import 'package:workmanager/workmanager.dart';

import 'core/node.dart';

/// Background check for new letters, with no server of ours involved.
///
/// The app writes `watch.json` (address, the last block it looked at, node
/// URLs) whenever it refreshes. A periodic task, run by Android's WorkManager
/// or iOS's background refresh, reads that file, asks a node for letters to
/// the address since that block, and posts a local notification with the
/// count on the app icon. Opening the inbox clears it. The node learns
/// nothing it did not already know: it serves the same query the app makes.
const backgroundTaskName = 'link.berrychain.wallet.refresh'; // must match BGTaskSchedulerPermittedIdentifiers on iOS
const _uniqueName = 'berry-inbox-check';
const _channelId = 'letters';

final notifications = FlutterLocalNotificationsPlugin();

Future<void> initNotifications() async {
  await notifications.initialize(
    settings: const InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
      iOS: DarwinInitializationSettings(requestAlertPermission: false, requestBadgePermission: false, requestSoundPermission: false),
    ),
  );
}

/// Ask for permission (Android 13+ and iOS) and schedule the periodic check.
Future<void> enableBackgroundChecks() async {
  final android = notifications.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
  await android?.requestNotificationsPermission();
  final ios = notifications.resolvePlatformSpecificImplementation<IOSFlutterLocalNotificationsPlugin>();
  await ios?.requestPermissions(alert: true, badge: true, sound: false);
  await Workmanager().registerPeriodicTask(
    _uniqueName,
    backgroundTaskName,
    frequency: const Duration(minutes: 15),
    initialDelay: const Duration(minutes: 5),
    constraints: Constraints(networkType: NetworkType.connected),
    existingWorkPolicy: ExistingPeriodicWorkPolicy.keep,
  );
}

Future<void> disableBackgroundChecks() async {
  await Workmanager().cancelByUniqueName(_uniqueName);
  await notifications.cancelAll();
}

/// Remember where the app got to, so the background task only reports
/// letters that arrived later. Also clears any badge, since the user is here.
Future<void> markSeen({required String address, required int height, required List<String> nodes}) async {
  final d = await getApplicationDocumentsDirectory();
  await File('${d.path}/watch.json').writeAsString(jsonEncode({'address': address, 'height': height, 'nodes': nodes, 'seen': 0}));
  await notifications.cancelAll();
}

/// The background entry point. Runs in its own isolate with no app state.
@pragma('vm:entry-point')
void callbackDispatcher() {
  Workmanager().executeTask((task, inputData) async {
    try {
      return await checkForLetters();
    } catch (_) {
      return true; // a failed check is not a failed job; try again next time
    }
  });
}

/// Returns true always (WorkManager retries on false); the outcome is the
/// notification, or nothing.
Future<bool> checkForLetters() async {
  final d = await getApplicationDocumentsDirectory();
  final f = File('${d.path}/watch.json');
  if (!await f.exists()) return true;
  final w = jsonDecode(await f.readAsString()) as Map<String, dynamic>;
  final address = w['address'] as String;
  final since = (w['height'] as int) + 1;
  final nodes = ((w['nodes'] as List?) ?? const ['https://seed1.berrychain.link', 'https://seed2.berrychain.link']).cast<String>();
  List<Map<String, dynamic>>? letters;
  for (final url in nodes) {
    try {
      letters = await Node(url, timeout: const Duration(seconds: 15)).letters(to: address, since: since);
      break;
    } catch (_) {}
  }
  if (letters == null) return true;
  final fresh = letters.where((l) => l['from'] != address).length;
  final already = (w['seen'] as int?) ?? 0;
  if (fresh == 0 || fresh == already) return true;
  await initNotifications();
  await notifications.show(
    id: 1,
    title: fresh == 1 ? 'A letter has arrived' : '$fresh letters have arrived',
    body: fresh == 1 ? 'Sealed, and waiting for you.' : 'Sealed, and waiting for you.',
    notificationDetails: NotificationDetails(
      android: AndroidNotificationDetails(_channelId, 'Letters',
          channelDescription: 'A quiet note when a sealed letter reaches your address',
          importance: Importance.defaultImportance, priority: Priority.defaultPriority, number: fresh, onlyAlertOnce: true),
      iOS: DarwinNotificationDetails(badgeNumber: fresh),
    ),
  );
  await f.writeAsString(jsonEncode({...w, 'seen': fresh}));
  if (kDebugMode) debugPrint('background check: $fresh new letter(s)');
  return true;
}
