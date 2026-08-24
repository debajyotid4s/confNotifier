package com.call4paper.app.data.local

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class TokenManager @Inject constructor(@ApplicationContext private val ctx: Context) {
    private val prefs: SharedPreferences by lazy {
        val masterKey = MasterKey.Builder(ctx).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
        EncryptedSharedPreferences.create(
            ctx, "auth_enc_prefs", masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }
    private val _flow = MutableStateFlow<String?>(null)
    val tokenFlow: Flow<String?> = _flow.map { it }
    val currentToken: String? get() = _flow.value

    init {
        _flow.value = prefs.getString("app_token", null)
    }

    suspend fun save(token: String) = withContext(Dispatchers.IO) {
        prefs.edit().putString("app_token", token).apply()
        _flow.value = token
    }
    suspend fun clear() = withContext(Dispatchers.IO) {
        prefs.edit().remove("app_token").apply()
        _flow.value = null
    }
    suspend fun peek(): String? = withContext(Dispatchers.IO) { prefs.getString("app_token", null) }
}
