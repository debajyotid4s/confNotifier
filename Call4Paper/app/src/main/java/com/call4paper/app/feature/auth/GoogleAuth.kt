package com.call4paper.app.feature.auth

import android.content.Context
import android.util.Log
import androidx.credentials.CredentialManager
import androidx.credentials.GetCredentialRequest
import com.google.android.libraries.identity.googleid.GetGoogleIdOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private const val TAG = "GoogleAuth"

// Web client ID from Firebase console → Project settings → General → Web SDK configuration
private const val WEB_CLIENT_ID = "203119671824-n3jbcp0paouibc1dbg1v4dmnpf9sm16s.apps.googleusercontent.com"

suspend fun getGoogleIdToken(ctx: Context): String? = withContext(Dispatchers.Main) {
    try {
        val option = GetGoogleIdOption.Builder()
            .setFilterByAuthorizedAccounts(false)
            .setServerClientId(WEB_CLIENT_ID)
            .build()
        val request = GetCredentialRequest.Builder().addCredentialOption(option).build()
        val cm = CredentialManager.create(ctx)
        val result = cm.getCredential(ctx, request)
        val cred = GoogleIdTokenCredential.createFrom(result.credential.data)
        Log.d(TAG, "Google id_token obtained for ${cred.id}")
        cred.idToken
    } catch (e: Exception) {
        Log.e(TAG, "Google credential failed", e)
        null
    }
}
