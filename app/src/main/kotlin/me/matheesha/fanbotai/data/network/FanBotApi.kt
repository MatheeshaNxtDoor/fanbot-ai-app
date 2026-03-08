package me.matheesha.fanbotai.data.network

import me.matheesha.fanbotai.data.model.*
import retrofit2.Response
import retrofit2.http.*

interface FanBotApi {

    @GET("api/dash/init-status")
    suspend fun initStatus(): Response<InitStatusResponse>

    @POST("api/dash/login")
    suspend fun login(@Body body: LoginRequest): Response<LoginResponse>

    @POST("api/dash/logout")
    suspend fun logout(): Response<OkResponse>

    @GET("api/dash/me")
    suspend fun me(): Response<MeResponse>

    @POST("api/dash/register")
    suspend fun register(@Body body: RegisterRequest): Response<RegisterResponse>

    @POST("api/dash/setup-2fa")
    suspend fun setup2fa(@Body body: Setup2faRequest): Response<OkResponse>

    @POST("api/dash/change-password")
    suspend fun changePassword(@Body body: ChangePasswordRequest): Response<OkResponse>

    @GET("api/status")
    suspend fun getStatus(): Response<BotStatus>

    @POST("api/bot/start")
    suspend fun botStart(): Response<BotActionResponse>

    @POST("api/bot/stop")
    suspend fun botStop(): Response<BotActionResponse>

    @POST("api/bot/restart")
    suspend fun botRestart(): Response<BotActionResponse>

    @GET("api/config")
    suspend fun getConfig(): Response<Config>

    @POST("api/config")
    suspend fun updateConfig(@Body body: Map<String, @JvmSuppressWildcards Any>): Response<OkResponse>

    @GET("api/conversations")
    suspend fun getConversations(): Response<List<Conversation>>

    @POST("api/conversations/{userId}/toggle-mute")
    suspend fun toggleMute(@Path("userId") userId: Long): Response<ToggleMuteResponse>

    @GET("api/analytics")
    suspend fun getAnalytics(): Response<Analytics>

    @GET("api/notes")
    suspend fun getNotes(): Response<List<Note>>

    @POST("api/notes")
    suspend fun createNote(@Body body: NoteRequest): Response<NoteResponse>

    @PUT("api/notes/{id}")
    suspend fun updateNote(@Path("id") id: String, @Body body: NoteRequest): Response<NoteResponse>

    @DELETE("api/notes/{id}")
    suspend fun deleteNote(@Path("id") id: String): Response<OkResponse>

    @GET("api/today-schedule")
    suspend fun getTodaySchedule(): Response<TodaySchedule>

    @GET("api/breaks/{date}")
    suspend fun getBreaks(@Path("date") date: String): Response<List<Break>>

    @POST("api/breaks/{date}")
    suspend fun addBreak(@Path("date") date: String, @Body body: BreakRequest): Response<OkResponse>

    @DELETE("api/breaks/{date}/{idx}")
    suspend fun deleteBreak(@Path("date") date: String, @Path("idx") idx: Int): Response<OkResponse>

    @GET("api/auth/status")
    suspend fun getTelegramAuthStatus(): Response<TelegramAuthStatus>

    @POST("api/auth/submit")
    suspend fun submitTelegramAuth(@Body body: TelegramAuthSubmit): Response<OkResponse>

    @GET("api/users")
    suspend fun getUsers(): Response<List<DashboardUser>>

    @PUT("api/users/{uid}/permissions")
    suspend fun setPermissions(@Path("uid") uid: String, @Body body: PermissionsRequest): Response<OkResponse>

    @DELETE("api/users/{uid}")
    suspend fun deleteUser(@Path("uid") uid: String): Response<OkResponse>

    @GET("api/invites")
    suspend fun getInvites(): Response<List<Invite>>

    @POST("api/invites")
    suspend fun createInvite(@Body body: InviteRequest): Response<InviteResponse>

    @DELETE("api/invites/{code}")
    suspend fun deleteInvite(@Path("code") code: String): Response<OkResponse>

    @POST("api/device/register")
    suspend fun registerDevice(@Body body: DeviceRegisterRequest): Response<OkResponse>

    @POST("api/device/unregister")
    suspend fun unregisterDevice(@Body body: DeviceRegisterRequest): Response<OkResponse>

    @GET("api/device/tokens")
    suspend fun getDeviceTokens(): Response<List<DeviceTokenInfo>>
}

