package me.matheesha.fanbotai.fcm
}
    }
        manager.notify(System.currentTimeMillis().toInt(), notification)
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

            .build()
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentText(body)
            .setContentTitle(title)
            .setSmallIcon(R.drawable.ic_notification)
        val notification = NotificationCompat.Builder(this, channelId)

        )
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            this, 0, intent,
        val pendingIntent = PendingIntent.getActivity(
        }
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        val intent = Intent(this, MainActivity::class.java).apply {
    private fun showNotification(title: String, body: String, channelId: String) {

    }
        showNotification(title, body, channelId)

        val channelId = message.data["channel"] ?: "fanbot_alerts"
            ?: "New notification"
            ?: message.data["body"]
        val body = message.notification?.body
            ?: "FanBot"
            ?: message.data["title"]
        val title = message.notification?.title

        super.onMessageReceived(message)
    override fun onMessageReceived(message: RemoteMessage) {

    }
        }
            }
                repo.registerDevice(token, Build.MODEL)
                val repo = DeviceRepository(settings)
            CoroutineScope(Dispatchers.IO).launch {
        if (settings.getServerUrl().isNotEmpty() && settings.isLoggedIn()) {
        // Register with the server if we have credentials

        settings.setFcmToken(token)
        val settings = SettingsRepository.getInstance(applicationContext)
        super.onNewToken(token)
    override fun onNewToken(token: String) {

class FanBotFcmService : FirebaseMessagingService() {

import me.matheesha.fanbotai.ui.MainActivity
import me.matheesha.fanbotai.data.repository.DeviceRepository
import me.matheesha.fanbotai.data.local.SettingsRepository
import me.matheesha.fanbotai.R
import kotlinx.coroutines.launch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CoroutineScope
import com.google.firebase.messaging.RemoteMessage
import com.google.firebase.messaging.FirebaseMessagingService
import androidx.core.app.NotificationCompat
import android.os.Build
import android.content.Intent
import android.content.Context
import android.app.PendingIntent
import android.app.NotificationManager


