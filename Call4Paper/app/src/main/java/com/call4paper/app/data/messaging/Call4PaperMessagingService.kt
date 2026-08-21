package com.call4paper.app.data.messaging

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.call4paper.app.MainActivity
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class Call4PaperMessagingService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        // TODO: POST /devices { fcmToken: token } with Firebase ID token
    }

    override fun onMessageReceived(msg: RemoteMessage) {
        val title = msg.notification?.title ?: msg.data["title"] ?: "Call4Paper"
        val body = msg.notification?.body ?: msg.data["body"] ?: ""
        val type = msg.data["type"] ?: "conference" // conference | deadline_change | reminder
        showNotification(title, body, type)
    }

    private fun showNotification(title: String, body: String, type: String) {
        val channelId = when (type) {
            "deadline_change" -> "deadline_change"
            "reminder" -> "daily_digest"
            else -> "conference"
        }
        ensureChannel(channelId, titleFor(channelId))

        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            data = android.net.Uri.parse("call4paper://conference/open")
        }
        val pi = PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

        val notif = NotificationCompat.Builder(this, channelId)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(pi)
            .setAutoCancel(true)
            .build()

        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
            .notify(System.currentTimeMillis().toInt(), notif)
    }

    private fun titleFor(id: String) = when (id) {
        "deadline_change" -> "Deadline Updated"
        "daily_digest" -> "Daily Digest"
        else -> "New Conferences"
    }

    private fun ensureChannel(id: String, name: String) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val importance = when (id) {
                "deadline_change" -> NotificationManager.IMPORTANCE_HIGH
                "conference" -> NotificationManager.IMPORTANCE_DEFAULT
                else -> NotificationManager.IMPORTANCE_LOW
            }
            val ch = NotificationChannel(id, name, importance)
            (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).createNotificationChannel(ch)
        }
    }
}
