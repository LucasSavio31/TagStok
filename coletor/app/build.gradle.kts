plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "br.curso.tagstock"
    compileSdk = 34

    defaultConfig {
        // Pacote próprio do TagStock
        applicationId = "br.curso.tagstock"
        minSdk = 26          // MC3300R/MC3390R: Android 8.1 ou superior
        targetSdk = 34
        versionCode = 5
        versionName = "1.4"
    }

    // Chave fixa: cada versão nova instala por cima da anterior
    signingConfigs {
        getByName("debug") {
            storeFile = file("tagstock.p12")
            storeType = "pkcs12"
            storePassword = "tagstock"
            keyAlias = "tagstock"
            keyPassword = "tagstock"
        }
    }

    // Modo local: a tela do coletor (server/app/static/m.html) vai dentro do APK
    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("telaLocal").get().asFile)

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    // SDK RFID da Zebra (API3): app/libs/API3_LIB-release.aar
    implementation(fileTree(mapOf("dir" to "libs", "include" to listOf("*.aar", "*.jar"))))
    // O SDK RFID usa android.support.v4.content.LocalBroadcastManager (biblioteca de suporte antiga)
    implementation("com.android.support:localbroadcastmanager:28.0.0")
}

val copiarTelaLocal by tasks.registering(Copy::class) {
    from(rootProject.file("../server/app/static/m.html"))
    into(layout.buildDirectory.dir("telaLocal").get().asFile)
}
tasks.named("preBuild") { dependsOn(copiarTelaLocal) }
