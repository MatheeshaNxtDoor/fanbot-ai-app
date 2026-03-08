package me.matheesha.fanbotai.data.model

import com.google.gson.annotations.SerializedName

// ── Auth ──────────────────────────────────────────────────────────────────────

data class LoginRequest(val username: String, val password: String, val totp: String? = null)

data class LoginUser(val username: String, val role: String)
data class LoginResponse(
    val ok: Boolean? = null,
    val error: String? = null,
    val needsTotp: Boolean? = null,
    val user: LoginUser? = null
)

data class RegisterRequest(val username: String, val password: String, @SerializedName("invite_code") val inviteCode: String? = null)
data class RegisterResponse(val ok: Boolean? = null, val error: String? = null)

data class Setup2faRequest(val uid: String, val token: String)
data class ChangePasswordRequest(@SerializedName("old_password") val oldPassword: String, @SerializedName("new_password") val newPassword: String)

data class MeResponse(val username: String = "", val role: String = "")
data class InitStatusResponse(val initialized: Boolean = false, val requireInvite: Boolean = false)
data class OkResponse(val ok: Boolean = true, val message: String = "")

// ── Bot ───────────────────────────────────────────────────────────────────────

data class BotStatus(
    val botRunning: Boolean = false,
    val windowState: String = "",
    val windowNext: String = "",
    val forceInactive: Boolean = false,
    val totalMessages: Int = 0,
    val totalReplies: Int = 0,
    val totalUsers: Int = 0,
    val messagesToday: Int = 0,
    val timezone: String = ""
)

data class BotActionResponse(val ok: Boolean = true, val message: String = "")

// ── Config ────────────────────────────────────────────────────────────────────

data class Config(val data: Map<String, Any> = emptyMap())

// ── Conversations ─────────────────────────────────────────────────────────────

data class Conversation(
    val userId: Long = 0,
    val name: String = "",
    val username: String = "",
    val lastMessage: String = "",
    val messageCount: Int = 0,
    val replyCount: Int = 0,
    val lastActive: String = "",
    val muted: Boolean = false
)

data class ToggleMuteResponse(val ok: Boolean = true, val muted: Boolean = false)

// ── Analytics ─────────────────────────────────────────────────────────────────

data class AnalyticsSummary(
    val totalMessages: Int = 0,
    val totalReplies: Int = 0,
    val totalUsers: Int = 0,
    val avgPerDay: Int = 0,
    val topUser: String = "",
    val topUserCount: Int = 0,
    val peakHour: String = "",
    val responseRate: Int = 0,
    val newToday: Int = 0
)

data class TopChatter(val name: String = "", val count: Int = 0)

data class Analytics(
    val summary: AnalyticsSummary = AnalyticsSummary(),
    val dailyLabels: List<String> = emptyList(),
    val dailyValues: List<Int> = emptyList(),
    val hourlyValues: List<Int> = emptyList(),
    val topChatters: List<TopChatter> = emptyList()
)

// ── Notes ─────────────────────────────────────────────────────────────────────

data class Note(val id: String = "", val date: String = "", val time: String = "", val title: String = "", val content: String = "")
data class NoteRequest(val date: String, val time: String, val title: String, val content: String)
data class NoteResponse(val ok: Boolean = true, val note: Note? = null)

// ── Schedule ──────────────────────────────────────────────────────────────────

data class Break(val start: String = "", val end: String = "")
data class BreakRequest(val start: String, val end: String)
data class TodaySchedule(val date: String = "", val windowStart: String = "", val windowEnd: String = "", val breaks: List<Break> = emptyList())

// ── Users ─────────────────────────────────────────────────────────────────────

data class DashboardUser(val id: String = "", val username: String = "", val role: String = "", val permissions: List<String> = emptyList(), val totpEnabled: Boolean = false)
data class PermissionsRequest(val permissions: List<String>)

data class Invite(val code: String = "", val permissions: List<String> = emptyList(), val createdAt: String = "")
data class InviteRequest(val permissions: List<String>)
data class InviteResponse(val ok: Boolean = true, val code: String = "")

// ── Devices ───────────────────────────────────────────────────────────────────

data class DeviceRegisterRequest(val token: String, val label: String = "")
data class DeviceTokenInfo(val token: String = "", val label: String = "", val createdAt: String = "")

// ── Telegram Auth ─────────────────────────────────────────────────────────────

data class TelegramAuthStatus(val status: String = "")
data class TelegramAuthSubmit(val value: String = "")

