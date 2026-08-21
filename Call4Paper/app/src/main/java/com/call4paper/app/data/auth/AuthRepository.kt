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
