package com.call4paper.app.data.remote

import kotlinx.serialization.Serializable
import retrofit2.http.*

@Serializable
data class GoogleAuthRequest(val id_token: String)

@Serializable
data class AuthResponse(val token: String, val user: UserDto)

@Serializable
data class UserDto(val id: String, val username: String, val email: String, val created_at: String? = null)

@Serializable
data class ConferenceDto(
    val id: Int,
    val name: String,
    val start_date: String? = null,
    val end_date: String? = null,
    val website: String? = null,
    val location: String? = null,
    val status: String? = null,
    val organizer: String? = null,
    val category: String? = null,
    val abstract_deadline: String? = null,
    val full_paper_deadline: String? = null,
    val description: String? = null
)

interface ApiService {
    @POST("auth/google")
    suspend fun authGoogle(@Body body: GoogleAuthRequest): AuthResponse

    @POST("auth/logout")
    suspend fun logout()

    @GET("me")
    suspend fun getMe(): UserDto

    @retrofit2.http.DELETE("me")
    suspend fun deleteMe(): Map<String, Boolean>

    @GET("conferences/calendar")
    suspend fun getCalendar(@Query("month") month: String): List<ConferenceDto>

    @GET("conferences/upcoming")
    suspend fun getUpcoming(@Query("limit") limit: Int = 30): List<ConferenceDto>

    @GET("conferences/{id}")
    suspend fun getConference(@Path("id") id: Int): ConferenceDto

    @GET("me/bookmarks")
    suspend fun getBookmarks(): List<ConferenceDto>

    @POST("me/bookmarks/{id}")
    suspend fun addBookmark(@Path("id") id: Int): Map<String, Boolean>

    @retrofit2.http.DELETE("me/bookmarks/{id}")
    suspend fun removeBookmark(@Path("id") id: Int)

    @POST("me/devices")
    suspend fun postDevice(@Body body: Map<String, String>): Map<String, Boolean>

    @retrofit2.http.DELETE("me/devices/{token}")
    suspend fun deleteDevice(@Path("token") token: String)
}
