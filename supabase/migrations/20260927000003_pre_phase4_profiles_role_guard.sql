-- ============================================================
-- ChargePlus — Pre-Phase-4 Remediation Gate (R6)
-- Database trigger guarding public.profiles.role
-- ============================================================
-- Finding: role protection relied on column-level REVOKE/GRANT
-- (Step 1.7 section 1.5) plus an insert WITH CHECK pinning role to
-- 'user'. The update policy (profiles_update_own) constrains only the
-- row id, so a future grant mistake could reopen self-promotion.
--
-- Fix: BEFORE trigger that rejects any role change unless the caller
-- is privileged (service_role/postgres, which bypass RLS and own role
-- management) or an authenticated admin. Normal profile edits from
-- Phase 3 (display_name, preferred_language, home_city) leave role
-- untouched and pass through. No RLS policy text changes, so no
-- existing client behavior changes except blocked escalation.
-- ============================================================

BEGIN;

CREATE OR REPLACE FUNCTION public.guard_profiles_role()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  -- INSERT: role must start as 'user' unless privileged/admin.
  IF TG_OP = 'INSERT' THEN
    IF NEW.role IS DISTINCT FROM 'user'
       AND current_user NOT IN ('service_role', 'postgres')
       AND NOT EXISTS (SELECT 1 FROM public.profiles p
                       WHERE p.id = auth.uid() AND p.role = 'admin') THEN
      RAISE EXCEPTION 'profiles.role must default to user for non-admin callers';
    END IF;
    RETURN NEW;
  END IF;

  -- UPDATE: role must be unchanged unless privileged/admin.
  IF NEW.role IS DISTINCT FROM OLD.role THEN
    IF current_user IN ('service_role', 'postgres') THEN
      RETURN NEW;
    END IF;
    IF EXISTS (SELECT 1 FROM public.profiles p
               WHERE p.id = auth.uid() AND p.role = 'admin') THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'profiles.role change denied for non-admin caller';
  END IF;
  RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_profiles_role_guard ON public.profiles;
CREATE TRIGGER trg_profiles_role_guard
  BEFORE INSERT OR UPDATE OF role ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION public.guard_profiles_role();

-- Self-verifying assertion: trigger present and bound to profiles.
DO $$
DECLARE
  v_count integer;
BEGIN
  SELECT count(*) INTO v_count
  FROM pg_trigger
  WHERE tgname = 'trg_profiles_role_guard'
    AND tgrelid = 'public.profiles'::regclass
    AND NOT tgisinternal;
  IF v_count <> 1 THEN
    RAISE EXCEPTION 'R6: trg_profiles_role_guard missing on public.profiles';
  END IF;
END
$$;

COMMIT;
