package com.call4paper.app.data.auth

import android.util.Log
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.auth.FirebaseUser
import kotlinx.coroutines.tasks.await
import javax.inject.Inject
import javax.inject.Singleton

private const val TAG = "AuthRepository"

@Singleton
class AuthRepository @Inject constructor(
    private val auth: FirebaseAuth
) {
    val currentUser: FirebaseUser? get() = auth.currentUser

    suspend fun signUp(email: String, password: String): Result<FirebaseUser> {
        Log.d(TAG, "signUp: attempt for $email")
        return try {
            val result = auth.createUserWithEmailAndPassword(email.trim(), password).await()
            val user = result.user
            if (user != null) {
                try {
                    user.sendEmailVerification().await()
                    Log.i(TAG, "signUp: verification email sent to ${user.email}")
                } catch (e: Exception) {
                    Log.w(TAG, "signUp: sendEmailVerification failed for ${user.email}", e)
                }
                Log.i(TAG, "signUp: success uid=${user.uid} email=${user.email}")
                Result.success(user)
            } else {
                Log.w(TAG, "signUp: null user after creation for $email")
                Result.failure(Exception("Sign up failed: no user"))
            }
        } catch (e: Exception) {
            Log.e(TAG, "signUp: failed for $email", e)
            Result.failure(e)
        }
    }

    suspend fun resendVerification(): Boolean {
        val user = auth.currentUser ?: return false
        return try {
            user.sendEmailVerification().await()
            true
        } catch (e: Exception) {
            Log.e(TAG, "resendVerification failed", e)
            false
        }
    }

    suspend fun reloadAndCheckVerified(): Boolean {
        val user = auth.currentUser ?: return false
        return try {
            user.reload().await()
            auth.currentUser?.isEmailVerified == true
        } catch (e: Exception) {
            Log.e(TAG, "reloadAndCheckVerified failed", e)
            false
        }
    }

    suspend fun sendPasswordReset(email: String): Result<Unit> {
        return try {
            auth.sendPasswordResetEmail(email.trim()).await()
            Log.i(TAG, "password reset sent to $email")
            Result.success(Unit)
        } catch (e: Exception) {
            Log.e(TAG, "sendPasswordReset failed for $email", e)
            Result.failure(e)
        }
    }

    suspend fun signIn(email: String, password: String): Result<FirebaseUser> {
        Log.d(TAG, "signIn: attempt for $email")
        return try {
            val result = auth.signInWithEmailAndPassword(email.trim(), password).await()
            val user = result.user
            if (user != null) {
                Log.i(TAG, "signIn: success uid=${user.uid} email=${user.email}")
                Result.success(user)
            } else {
                Log.w(TAG, "signIn: null user after sign-in for $email")
                Result.failure(Exception("Sign in failed: no user"))
            }
        } catch (e: Exception) {
            Log.e(TAG, "signIn: failed for $email", e)
            Result.failure(e)
        }
    }

    fun signOut() {
        Log.d(TAG, "signOut: uid=${auth.currentUser?.uid}")
        auth.signOut()
    }
}
