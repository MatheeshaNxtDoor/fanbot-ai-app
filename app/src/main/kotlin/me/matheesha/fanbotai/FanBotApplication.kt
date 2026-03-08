package me.matheesha.fanbotai

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context

class FanBotApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        createNotificationChannels()
    }

    private fun createNotificationChannels() {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(
            NotificationChannel("fanbot_alerts", "FanBot Alerts", NotificationManager.IMPORTANCE_HIGH)
                .apply { description = "Bot activity alerts" }
        )
        manager.createNotificationChannel(
            NotificationChannel("fanbot_general", "General", NotificationManager.IMPORTANCE_DEFAULT)
                .apply { description = "General notifications" }
        )
    }
}

