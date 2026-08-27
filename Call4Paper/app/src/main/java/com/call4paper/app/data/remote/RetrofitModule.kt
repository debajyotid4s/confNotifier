package com.call4paper.app.data.remote

import com.call4paper.app.data.local.TokenManager
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import kotlinx.serialization.json.Json
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    @Provides @Singleton
    fun provideOkHttp(tokenManager: TokenManager): OkHttpClient {
        val authInterceptor = Interceptor { chain ->
            val token = tokenManager.currentToken
            val req = if (!token.isNullOrBlank()) chain.request().newBuilder().addHeader("Authorization", "Bearer $token").build() else chain.request()
            chain.proceed(req)
        }
        // Cold-start resilience: Render free sleeps after ~15 min; wake is 30-50s.
        // Retry once on SocketTimeout for POST /auth/login only — that endpoint
        // is safe to retry (server is idempotent on google_subject_id) and is
        // exactly where users see "first fails, second succeeds".
        val coldStartRetry = Interceptor { chain ->
            val req = chain.request()
            val isAuthLogin = req.method == "POST" && req.url.encodedPath.endsWith("/auth/login")
            try {
                chain.proceed(req)
            } catch (e: java.net.SocketTimeoutException) {
                if (isAuthLogin && req.header("X-Retry") == null) {
                    chain.proceed(req.newBuilder().header("X-Retry", "1").build())
                } else throw e
            }
        }
        val logging = HttpLoggingInterceptor().apply {
            level = if (com.call4paper.app.BuildConfig.DEBUG) HttpLoggingInterceptor.Level.BODY else HttpLoggingInterceptor.Level.NONE
        }
        return OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .addInterceptor(authInterceptor)
            .addInterceptor(coldStartRetry)
            .addInterceptor(logging)
            .build()
    }

    @Provides @Singleton
    fun provideRetrofit(okHttp: OkHttpClient): Retrofit {
        val baseUrl = "https://confnotifier.onrender.com/"
        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(okHttp)
            .addConverterFactory(Json { ignoreUnknownKeys = true }.asConverterFactory("application/json".toMediaType()))
            .build()
    }

    @Provides @Singleton
    fun provideApi(retrofit: Retrofit): ApiService = retrofit.create(ApiService::class.java)
}
