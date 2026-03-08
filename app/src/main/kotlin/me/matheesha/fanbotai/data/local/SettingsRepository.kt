package me.matheesha.fanbotai.data.local

import android.content.Context
import android.content.SharedPreferences

class SettingsRepository(context: Context) {

    private val prefs: SharedPreferences =
        context.getSharedPreferences("fanbot_settings", Context.MODE_PRIVATE)

    fun getServerUrl(): String = prefs.getString(KEY_SERVER_URL, "") ?: ""
    fun setServerUrl(url: String) = prefs.edit().putString(KEY_SERVER_URL, url).apply()

    fun getApiKey(): String = prefs.getString(KEY_API_KEY, "") ?: ""
    fun setApiKey(key: String) = prefs.edit().putString(KEY_API_KEY, key).apply()

    fun getFcmToken(): String = prefs.getString(KEY_FCM_TOKEN, "") ?: ""
    fun setFcmToken(token: String) = prefs.edit().putString(KEY_FCM_TOKEN, token).apply()

    fun isLoggedIn(): Boolean = prefs.getBoolean(KEY_LOGGED_IN, false)
    fun setLoggedIn(v: Boolean) = prefs.edit().putBoolean(KEY_LOGGED_IN, v).apply()

    fun getSavedUsername(): String = prefs.getString(KEY_USERNAME, "") ?: ""
    fun setSavedUsername(u: String) = prefs.edit().putString(KEY_USERNAME, u).apply()

    fun getSavedRole(): String = prefs.getString(KEY_ROLE, "user") ?: "user"
    fun setSavedRole(r: String) = prefs.edit().putString(KEY_ROLE, r).apply()

    fun clearSession() {
        prefs.edit().remove(KEY_LOGGED_IN).remove(KEY_USERNAME).remove(KEY_ROLE).apply()
    }

    companion object {
        private const val KEY_SERVER_URL = "server_url"
        private const val KEY_API_KEY    = "api_key"
        private const val KEY_FCM_TOKEN  = "fcm_token"
        private const val KEY_LOGGED_IN  = "logged_in"
        private const val KEY_USERNAME   = "username"
        private const val KEY_ROLE       = "role"

        @Volatile private var INSTANCE: SettingsRepository? = null

        fun getInstance(context: Context): SettingsRepository =
            INSTANCE ?: synchronized(this) {
                INSTANCE ?: SettingsRepository(context.applicationContext).also { INSTANCE = it }
            }
    }
}

