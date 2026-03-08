package me.matheesha.fanbotai.data.network

import me.matheesha.fanbotai.data.local.SettingsRepository
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

object ApiClient {

    @Volatile private var retrofit: Retrofit? = null
    @Volatile private var lastUrl: String = ""
    @Volatile private var lastKey: String = ""

    fun getApi(settings: SettingsRepository): FanBotApi {
        val url = settings.getServerUrl().trimEnd('/') + "/"
        val key = settings.getApiKey()

        if (retrofit == null || url != lastUrl || key != lastKey) {
            synchronized(this) {
                if (retrofit == null || url != lastUrl || key != lastKey) {
                    lastUrl = url
                    lastKey = key
                    retrofit = buildRetrofit(url, key)
                }
            }
        }
        return retrofit!!.create(FanBotApi::class.java)
    }

    fun invalidate() {
        synchronized(this) { retrofit = null }
    }

    private fun buildRetrofit(baseUrl: String, apiKey: String): Retrofit {
        val logging = HttpLoggingInterceptor().apply { level = HttpLoggingInterceptor.Level.BASIC }

        val client = OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .addInterceptor { chain ->
                val request = chain.request().newBuilder()
                    .addHeader("X-API-Key", apiKey)
                    .build()
                chain.proceed(request)
            }
            .addInterceptor(logging)
            .build()

        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
    }
}

