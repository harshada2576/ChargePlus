"use client";

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

export default function SupabaseTestPage() {
    const [status, setStatus] = useState("Testing...");
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        async function testSupabase() {
            const { data, error } = await supabase.auth.getSession();

            if (error) {
                setStatus("Supabase connection failed");
                setError(error.message);
                return;
            }

            setStatus("Supabase connection successful");

            console.log("Supabase session:", data.session);
        }

        testSupabase();
    }, []);

    return (
        <main style={{ padding: 40 }}>
            <h1>{status}</h1>

            {error && (
                <pre style={{ marginTop: 20 }}>
                    {error}
                </pre>
            )}

            {!error && (
                <p>
                    No logged-in user is expected yet.
                </p>
            )}
        </main>
    );
}