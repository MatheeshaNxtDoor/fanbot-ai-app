package me.matheesha.fanbotai.data.repository

import me.matheesha.fanbotai.data.local.SettingsRepository
import me.matheesha.fanbotai.data.model.*
import me.matheesha.fanbotai.data.network.ApiClient

sealed class Result<out T> {
    data class Success<T>(val data: T) : Result<T>()
    data class Error(val message: String, val code: Int = 0) : Result<Nothing>()
}

suspend fun <T> safeApiCall(call: suspend () -> retrofit2.Response<T>): Result<T> {
    return try {
        val response = call()
        if (response.isSuccessful) {
            val body = response.body()
            if (body != null) Result.Success(body)
            else Result.Error("Empty response body", response.code())
        } else {
            Result.Error(response.message().ifEmpty { "Server error" }, response.code())
        }
    } catch (e: Exception) {
        Result.Error(e.localizedMessage ?: "Unknown error")
    }
}

class AuthRepository(private val settings: SettingsRepository) {
    private fun api() = ApiClient.getApi(settings)
    suspend fun initStatus() = safeApiCall { api().initStatus() }
    suspend fun login(username: String, password: String, totp: String? = null) =
        safeApiCall { api().login(LoginRequest(username, password, totp)) }
    suspend fun logout() = safeApiCall { api().logout() }
    suspend fun me() = safeApiCall { api().me() }
    suspend fun register(username: String, password: String, inviteCode: String?) =
        safeApiCall { api().register(RegisterRequest(username, password, inviteCode)) }
    suspend fun setup2fa(uid: String, token: String) =
        safeApiCall { api().setup2fa(Setup2faRequest(uid, token)) }
    suspend fun changePassword(oldPass: String, newPass: String) =
        safeApiCall { api().changePassword(ChangePasswordRequest(oldPass, newPass)) }
}

class BotRepository(private val settings: SettingsRepository) {
    private fun api() = ApiClient.getApi(settings)
    suspend fun getStatus() = safeApiCall { api().getStatus() }
    suspend fun start()   = safeApiCall { api().botStart() }
    suspend fun stop()    = safeApiCall { api().botStop() }
    suspend fun restart() = safeApiCall { api().botRestart() }
}

class ConfigRepository(private val settings: SettingsRepository) {
    private fun api() = ApiClient.getApi(settings)
    suspend fun getConfig() = safeApiCall { api().getConfig() }
    suspend fun updateConfig(patch: Map<String, Any>) = safeApiCall { api().updateConfig(patch) }
}

class ConversationRepository(private val settings: SettingsRepository) {
    private fun api() = ApiClient.getApi(settings)
    suspend fun getConversations() = safeApiCall { api().getConversations() }
    suspend fun toggleMute(userId: Long) = safeApiCall { api().toggleMute(userId) }
}

class AnalyticsRepository(private val settings: SettingsRepository) {
    private fun api() = ApiClient.getApi(settings)
    suspend fun getAnalytics() = safeApiCall { api().getAnalytics() }
}

class NotesRepository(private val settings: SettingsRepository) {
    private fun api() = ApiClient.getApi(settings)
    suspend fun getNotes() = safeApiCall { api().getNotes() }
    suspend fun createNote(date: String, time: String, title: String, content: String) =
        safeApiCall { api().createNote(NoteRequest(date, time, title, content)) }
    suspend fun updateNote(id: String, date: String, time: String, title: String, content: String) =
        safeApiCall { api().updateNote(id, NoteRequest(date, time, title, content)) }
    suspend fun deleteNote(id: String) = safeApiCall { api().deleteNote(id) }
}

class ScheduleRepository(private val settings: SettingsRepository) {
    private fun api() = ApiClient.getApi(settings)
    suspend fun getTodaySchedule() = safeApiCall { api().getTodaySchedule() }
    suspend fun getBreaks(date: String) = safeApiCall { api().getBreaks(date) }
    suspend fun addBreak(date: String, start: String, end: String) =
        safeApiCall { api().addBreak(date, BreakRequest(start, end)) }
    suspend fun deleteBreak(date: String, idx: Int) = safeApiCall { api().deleteBreak(date, idx) }
}

class UsersRepository(private val settings: SettingsRepository) {
    private fun api() = ApiClient.getApi(settings)
    suspend fun getUsers() = safeApiCall { api().getUsers() }
    suspend fun setPermissions(uid: String, permissions: List<String>) =
        safeApiCall { api().setPermissions(uid, PermissionsRequest(permissions)) }
    suspend fun deleteUser(uid: String) = safeApiCall { api().deleteUser(uid) }
    suspend fun getInvites() = safeApiCall { api().getInvites() }
    suspend fun createInvite(permissions: List<String>) =
        safeApiCall { api().createInvite(InviteRequest(permissions)) }
    suspend fun deleteInvite(code: String) = safeApiCall { api().deleteInvite(code) }
}

class DeviceRepository(private val settings: SettingsRepository) {
    private fun api() = ApiClient.getApi(settings)
    suspend fun registerDevice(token: String, label: String) =
        safeApiCall { api().registerDevice(DeviceRegisterRequest(token, label)) }
    suspend fun unregisterDevice(token: String) =
        safeApiCall { api().unregisterDevice(DeviceRegisterRequest(token)) }
}

