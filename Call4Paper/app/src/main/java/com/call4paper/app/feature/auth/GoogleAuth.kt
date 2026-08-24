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

private val WEB_CLIENT_ID: String
    get() = com.call4paper.app.BuildConfig.WEB_CLIENT_ID

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
