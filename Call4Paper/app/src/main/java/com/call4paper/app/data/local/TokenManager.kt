package com.call4paper.app.data.local

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withContext
import java.security.KeyStore
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class TokenManager @Inject constructor(@ApplicationContext private val ctx: Context) {
    private val prefs: SharedPreferences by lazy { initPrefs() }

    private fun initPrefs(): SharedPreferences {
        val spDir = java.io.File(ctx.applicationInfo.dataDir, "shared_prefs")
        try {
            java.io.File(spDir, "auth_enc_prefs.xml").delete()
            java.io.File(spDir, "auth_enc_prefs__master_key_backup.xml").delete()
        } catch (_: Exception) {}
        try {
            val keyStore = KeyStore.getInstance("AndroidKeyStore")
            keyStore.load(null)
            keyStore.deleteEntry(DEFAULT_MASTER_KEY_ALIAS)
            keyStore.deleteEntry(CUSTOM_MASTER_KEY_ALIAS)
        } catch (_: Exception) {}

        return try {
            val masterKey = MasterKey.Builder(ctx, CUSTOM_MASTER_KEY_ALIAS)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            EncryptedSharedPreferences.create(
                ctx, "auth_enc_prefs", masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
            )
        } catch (e: Exception) {
            Log.w("TokenManager", "EncryptedPrefs unrecoverable, falling back to plain SP", e)
            ctx.getSharedPreferences("auth_plain_prefs", Context.MODE_PRIVATE)
        }
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

    companion object {
        private const val DEFAULT_MASTER_KEY_ALIAS = "__androidx_security_crypto_encrypted_prefs_key_keyset__"
        private const val CUSTOM_MASTER_KEY_ALIAS = "call4paper_master_key"
    }
}
