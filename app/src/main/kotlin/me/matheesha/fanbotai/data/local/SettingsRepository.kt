package me.matheesha.fanbotai.data.local
}
    }
            }
                INSTANCE ?: SettingsRepository(context.applicationContext).also { INSTANCE = it }
            INSTANCE ?: synchronized(this) {
        fun getInstance(context: Context): SettingsRepository =
        @Volatile private var INSTANCE: SettingsRepository? = null

        private const val KEY_ROLE       = "role"
        private const val KEY_USERNAME   = "username"
        private const val KEY_LOGGED_IN  = "logged_in"
        private const val KEY_FCM_TOKEN  = "fcm_token"
        private const val KEY_API_KEY    = "api_key"
        private const val KEY_SERVER_URL = "server_url"
    companion object {

    }
            .apply()
            .remove(KEY_ROLE)
            .remove(KEY_USERNAME)
            .remove(KEY_LOGGED_IN)
        prefs.edit()
    fun clearSession() {

    fun setSavedRole(r: String) = prefs.edit().putString(KEY_ROLE, r).apply()
    fun getSavedRole(): String = prefs.getString(KEY_ROLE, "user") ?: "user"

    fun setSavedUsername(u: String) = prefs.edit().putString(KEY_USERNAME, u).apply()
    fun getSavedUsername(): String = prefs.getString(KEY_USERNAME, "") ?: ""

    fun setLoggedIn(v: Boolean) = prefs.edit().putBoolean(KEY_LOGGED_IN, v).apply()
    fun isLoggedIn(): Boolean = prefs.getBoolean(KEY_LOGGED_IN, false)

    fun setFcmToken(token: String) = prefs.edit().putString(KEY_FCM_TOKEN, token).apply()
    fun getFcmToken(): String = prefs.getString(KEY_FCM_TOKEN, "") ?: ""

    fun setApiKey(key: String) = prefs.edit().putString(KEY_API_KEY, key).apply()
    fun getApiKey(): String = prefs.getString(KEY_API_KEY, "") ?: ""

    fun setServerUrl(url: String) = prefs.edit().putString(KEY_SERVER_URL, url).apply()
    fun getServerUrl(): String = prefs.getString(KEY_SERVER_URL, "") ?: ""

        context.getSharedPreferences("fanbot_settings", Context.MODE_PRIVATE)
    private val prefs: SharedPreferences =

class SettingsRepository(context: Context) {

import android.content.SharedPreferences
import android.content.Context


