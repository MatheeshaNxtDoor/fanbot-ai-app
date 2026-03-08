package me.matheesha.fanbotai.fcm

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import me.matheesha.fanbotai.R
import me.matheesha.fanbotai.data.local.SettingsRepository
import me.matheesha.fanbotai.data.repository.DeviceRepository
import me.matheesha.fanbotai.ui.MainActivity

class FanBotFcmService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        super.onNewToken(token)
        val settings = SettingsRepository.getInstance(applicationContext)
        settings.setFcmToken(token)
        if (settings.getServerUrl().isNotEmpty() && settings.isLoggedIn()) {
            CoroutineScope(Dispatchers.IO).launch {
                DeviceRepository(settings).registerDevice(token, Build.MODEL)
            }
        }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        super.onMessageReceived(message)
        val title     = message.notification?.title ?: message.data["title"] ?: "FanBot"
        val body      = message.notification?.body  ?: message.data["body"]  ?: "New notification"
        val channelId = message.data["channel"] ?: "fanbot_alerts"
        showNotification(title, body, channelId)
    }

    private fun showNotification(title: String, body: String, channelId: String) {
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pi = PendingIntent.getActivity(
            this, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notification = NotificationCompat.Builder(this, channelId)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setAutoCancel(true)
            .setContentIntent(pi)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()
        (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
            .notify(System.currentTimeMillis().toInt(), notification)
    }
}

