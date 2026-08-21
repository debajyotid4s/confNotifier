package com.call4paper.app.feature.auth

import android.util.Log
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.launch

private const val TAG = "AuthScreens"

@Composable
fun LoginScreen(
    onNavigateToSignUp: () -> Unit,
    onLoggedIn: () -> Unit,
    vm: AuthViewModel = hiltViewModel()
) {
    val state by vm.uiState.collectAsStateWithLifecycle()
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    LaunchedEffect(state.isLoggedIn) { if (state.isLoggedIn) { Log.d(TAG, "LoginScreen: already logged in"); onLoggedIn() } }
    AuthForm(
        title = "Welcome back",
        subtitle = "Sign in to track deadlines",
        state = state,
        isSignUp = false,
        onEmailChange = vm::onEmailChange,
        onPasswordChange = vm::onPasswordChange,
        onConfirmChange = vm::onConfirmPasswordChange,
        onSubmit = { vm.signIn(onLoggedIn) },
        onGoogle = {
            scope.launch {
                Log.d(TAG, "LoginScreen: Google tapped")
                val token = getGoogleIdToken(ctx)
                if (token != null) vm.signInWithGoogle(token, onLoggedIn) else Log.w(TAG, "Google token null")
            }
        },
        onSwitch = onNavigateToSignUp,
        switchText = "Don't have an account? Sign up"
    )
}

@Composable
fun SignUpScreen(
    onNavigateToLogin: () -> Unit,
    onSignedUp: () -> Unit,
    vm: AuthViewModel = hiltViewModel()
) {
    val state by vm.uiState.collectAsStateWithLifecycle()
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    AuthForm(
        title = "Create account",
        subtitle = "Join to never miss a submission",
        state = state,
        isSignUp = true,
        onEmailChange = vm::onEmailChange,
        onPasswordChange = vm::onPasswordChange,
        onConfirmChange = vm::onConfirmPasswordChange,
        onSubmit = { vm.signUp(onSignedUp) },
        onGoogle = {
            scope.launch {
                Log.d(TAG, "SignUpScreen: Google tapped")
                val token = getGoogleIdToken(ctx)
                if (token != null) vm.signInWithGoogle(token, onSignedUp) else Log.w(TAG, "Google token null")
            }
        },
        onSwitch = onNavigateToLogin,
        switchText = "Already have an account? Sign in"
    )
}

@Composable
private fun AuthForm(
    title: String,
    subtitle: String,
    state: AuthUiState,
    isSignUp: Boolean,
    onEmailChange: (String) -> Unit,
    onPasswordChange: (String) -> Unit,
    onConfirmChange: (String) -> Unit,
    onSubmit: () -> Unit,
    onGoogle: () -> Unit,
    onSwitch: () -> Unit,
    switchText: String
) {
    var passVisible by remember { mutableStateOf(false) }
    var confirmVisible by remember { mutableStateOf(false) }
    val focus = LocalFocusManager.current

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 32.dp)
            .windowInsetsPadding(WindowInsets.statusBars)
            .windowInsetsPadding(WindowInsets.navigationBars)
            .windowInsetsPadding(WindowInsets.displayCutout),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Spacer(Modifier.height(32.dp))
        Text(title, style = MaterialTheme.typography.headlineMedium, fontSize = 28.sp)
        Spacer(Modifier.height(8.dp))
        Text(subtitle, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 14.sp)
        Spacer(Modifier.height(32.dp))

        OutlinedTextField(
            value = state.email,
            onValueChange = onEmailChange,
            label = { Text("Email", fontSize = 14.sp) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
            keyboardActions = KeyboardActions(onNext = { focus.moveFocus(FocusDirection.Down) }),
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(Modifier.height(16.dp))

        OutlinedTextField(
            value = state.password,
            onValueChange = onPasswordChange,
            label = { Text("Password", fontSize = 14.sp) },
            singleLine = true,
            visualTransformation = if (passVisible) VisualTransformation.None else PasswordVisualTransformation(),
            trailingIcon = {
                IconButton(onClick = { passVisible = !passVisible }) {
                    Icon(if (passVisible) Icons.Filled.VisibilityOff else Icons.Filled.Visibility, contentDescription = null)
                }
            },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = if (isSignUp) ImeAction.Next else ImeAction.Done),
            keyboardActions = KeyboardActions(
                onNext = { if (isSignUp) focus.moveFocus(FocusDirection.Down) else onSubmit() },
                onDone = { if (!isSignUp) onSubmit() }
            ),
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(Modifier.height(16.dp))

        if (isSignUp) {
            OutlinedTextField(
                value = state.confirmPassword,
                onValueChange = onConfirmChange,
                label = { Text("Confirm password", fontSize = 14.sp) },
                singleLine = true,
                visualTransformation = if (confirmVisible) VisualTransformation.None else PasswordVisualTransformation(),
                trailingIcon = {
                    IconButton(onClick = { confirmVisible = !confirmVisible }) {
                        Icon(if (confirmVisible) Icons.Filled.VisibilityOff else Icons.Filled.Visibility, contentDescription = null)
                    }
                },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { onSubmit() }),
                modifier = Modifier.fillMaxWidth()
            )
            Spacer(Modifier.height(16.dp))
        }

        if (state.errorMessage != null) {
            Text(state.errorMessage, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall, fontSize = 13.sp, modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.height(12.dp))
        }

        Button(
            onClick = { Log.d(TAG, "AuthForm: submit isSignUp=$isSignUp email=${state.email}"); onSubmit() },
            enabled = !state.isLoading,
            modifier = Modifier.fillMaxWidth().height(52.dp)
        ) {
            if (state.isLoading) CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
            else Text(if (isSignUp) "Create account" else "Sign in", fontSize = 16.sp)
        }
        Spacer(Modifier.height(12.dp))
        OutlinedButton(
            onClick = onGoogle,
            enabled = !state.isLoading,
            modifier = Modifier.fillMaxWidth().height(52.dp)
        ) { Text("Continue with Google", fontSize = 15.sp) }
        Spacer(Modifier.height(16.dp))

        TextButton(onClick = onSwitch, modifier = Modifier.fillMaxWidth()) {
            Text(switchText, fontSize = 14.sp)
        }
        Spacer(Modifier.height(24.dp))
        Text("By continuing you agree to our Terms", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 11.sp)
    }
}
